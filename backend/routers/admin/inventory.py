from datetime import datetime, timezone
from uuid import UUID

import asyncio
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.enums import InventoryStatus, LockerCellStatus, LockerStatus, RentalStatus, RentalEventSource
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.routers.admin.auth import get_current_admin
from backend.schemas.admin_panel_schemas import (
    AdminConfirmInventoryReadyPayload,
    AdminPlaceProductInCellPayload,
    AdminTakeForServicePayload,
)
from backend.utils.admin_audit import record_admin_audit
from backend.utils.esi_client import (
    EsiDiscoveryError,
    EsiOpenError,
    admin_trigger_open_cell,
    fetch_machine_snapshot,
    sync_cell_state,
)
from backend.utils.inventory_tracking import add_inventory_movement
from backend.utils.products_utils import load_media_files_by_ids, public_media_url

router = APIRouter(prefix="/api/admin/inventory", tags=["admin-inventory"])

_OPEN_ERR = {
    "CELL_NOT_FOUND": (404, "Ячейка не найдена"),
    "CELL_NOT_OPERABLE": (409, "Ячейку нельзя открыть, проверьте статус"),
    "ESI_NOT_CONFIGURED": (503, "Интеграция с постаматом не настроена"),
    "ESI_HTTP_ERROR": (502, "Ошибка связи с постаматом"),
    "ESI_OPEN_FAILED": (502, "Постамат отклонил команду открытия"),
    "ESI_CELL_OR_MACHINE_NOT_FOUND": (
        502,
        "Постамат или ячейка не найдены в ESI: проверьте серийный номер "
        "постамата и внешние ID ячеек (рассинхрон с провайдером)",
    ),
    "ESI_MACHINE_OFFLINE": (503, "Постамат сейчас offline"),
}


def _serialize_locker_summary(
    locker: LockerLocation,
    *,
    city_name: str | None,
    total_cells: int,
    free_cells: int,
    occupied_cells: int,
) -> dict:
    return {
        "id": str(locker.id),
        "name": locker.name,
        "address": locker.address,
        "cityId": str(locker.city_id),
        "cityName": city_name,
        "status": locker.status.value if isinstance(locker.status, LockerStatus) else str(locker.status),
        "totalCells": total_cells,
        "freeCells": free_cells,
        "occupiedCells": occupied_cells,
    }


def _serialize_cell_with_unit(
    cell: LockerCell,
    unit: InventoryUnit | None,
    product: Product | None,
    cover_url: str | None,
) -> dict:
    return {
        "id": str(cell.id),
        "label": cell.label,
        "externalCellId": cell.external_cell_id,
        "size": cell.size,
        "status": cell.status.value,
        "supportsReturn": cell.supports_return,
        "currentUnit": (
            {
                "id": str(unit.id),
                "status": unit.status.value,
                "serialNumber": unit.serial_number,
                "productId": str(unit.product_id),
                "productName": product.name if product else "",
                "productSlug": product.slug if product else None,
                "coverUrl": cover_url,
            }
            if unit is not None
            else None
        ),
    }


def _serialize_product_row(
    product: Product,
    category_name: str | None,
    available_units: int,
    total_units: int,
    cover_url: str | None,
) -> dict:
    return {
        "id": str(product.id),
        "name": product.name,
        "slug": product.slug,
        "isActive": product.is_active,
        "categoryId": str(product.category_id),
        "categoryName": category_name,
        "availableUnits": int(available_units),
        "totalUnits": int(total_units),
        "coverUrl": cover_url,
    }


@router.get("/lockers")
async def list_inventory_lockers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    lockers = (
        await db.scalars(
            select(LockerLocation).order_by(LockerLocation.name.asc())
        )
    ).all()
    if not lockers:
        return {"data": {"lockers": []}, "meta": {"total": 0}}

    locker_ids = [locker.id for locker in lockers]

    city_ids = list({locker.city_id for locker in lockers})
    city_map: dict[UUID, str] = {}
    if city_ids:
        cities = (await db.scalars(select(City).where(City.id.in_(city_ids)))).all()
        city_map = {city.id: city.name for city in cities}

    cells_stmt = (
        select(
            LockerCell.locker_id,
            LockerCell.status,
            func.count(LockerCell.id),
        )
        .where(LockerCell.locker_id.in_(locker_ids))
        .group_by(LockerCell.locker_id, LockerCell.status)
    )
    cell_rows = (await db.execute(cells_stmt)).all()

    totals: dict[UUID, dict[str, int]] = {
        locker_id: {"total": 0, "free": 0, "occupied": 0} for locker_id in locker_ids
    }
    for locker_id, status, cnt in cell_rows:
        totals.setdefault(locker_id, {"total": 0, "free": 0, "occupied": 0})
        totals[locker_id]["total"] += int(cnt)
        if status == LockerCellStatus.VACANT:
            totals[locker_id]["free"] += int(cnt)
        elif status == LockerCellStatus.OCCUPIED:
            totals[locker_id]["occupied"] += int(cnt)

    return {
        "data": {
            "lockers": [
                _serialize_locker_summary(
                    locker,
                    city_name=city_map.get(locker.city_id),
                    total_cells=totals.get(locker.id, {}).get("total", 0),
                    free_cells=totals.get(locker.id, {}).get("free", 0),
                    occupied_cells=totals.get(locker.id, {}).get("occupied", 0),
                )
                for locker in lockers
            ]
        },
        "meta": {"total": len(lockers)},
    }


@router.get("/lockers/{locker_id}/cells")
async def list_inventory_locker_cells(
    request: Request,
    locker_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    locker = await db.get(LockerLocation, locker_id)
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    cells = (
        await db.scalars(
            select(LockerCell)
            .where(LockerCell.locker_id == locker_id)
            .order_by(LockerCell.label.asc().nulls_last(), LockerCell.created_at.asc())
        )
    ).all()

    units_by_cell: dict[UUID, InventoryUnit] = {}
    if cells:
        units = (
            await db.scalars(
                select(InventoryUnit).where(
                    InventoryUnit.locker_cell_id.in_([c.id for c in cells])
                )
            )
        ).all()
        units_by_cell = {u.locker_cell_id: u for u in units if u.locker_cell_id}

    product_ids = list({u.product_id for u in units_by_cell.values()})
    product_map: dict[UUID, Product] = {}
    media_map = {}
    if product_ids:
        products = (
            await db.scalars(select(Product).where(Product.id.in_(product_ids)))
        ).all()
        product_map = {p.id: p for p in products}
        cover_ids = [p.cover_file_id for p in products if p.cover_file_id]
        if cover_ids:
            media_map = await load_media_files_by_ids(db, cover_ids)

    payload_cells = []
    for cell in cells:
        unit = units_by_cell.get(cell.id)
        product = product_map.get(unit.product_id) if unit else None
        cover_url = None
        if product and product.cover_file_id and product.cover_file_id in media_map:
            cover_url = public_media_url(media_map[product.cover_file_id].file_key)
        payload_cells.append(_serialize_cell_with_unit(cell, unit, product, cover_url))

    return {
        "data": {
            "locker": {
                "id": str(locker.id),
                "name": locker.name,
                "address": locker.address,
                "status": locker.status.value
                if isinstance(locker.status, LockerStatus)
                else str(locker.status),
            },
            "cells": payload_cells,
        }
    }


@router.get("/products")
async def list_inventory_products(
    request: Request,
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, max_length=200),
    category_id: UUID | None = Query(None, alias="categoryId"),
    only_active: bool = Query(True, alias="onlyActive"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
):
    await get_current_admin(request, db)

    filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters.append(or_(Product.name.ilike(term), Product.slug.ilike(term)))
    if category_id is not None:
        filters.append(Product.category_id == category_id)
    if only_active:
        filters.append(Product.is_active.is_(True))

    count_stmt = select(func.count()).select_from(Product)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await db.scalar(count_stmt)) or 0

    stmt = select(Product)
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.order_by(Product.name.asc()).offset((page - 1) * limit).limit(limit)
    products = (await db.scalars(stmt)).all()

    cat_ids = list({p.category_id for p in products})
    cat_by_id: dict[UUID, str] = {}
    if cat_ids:
        cats = (
            await db.scalars(
                select(ProductCategory).where(ProductCategory.id.in_(cat_ids))
            )
        ).all()
        cat_by_id = {c.id: c.name for c in cats}

    product_ids = [p.id for p in products]
    available_counts: dict[UUID, int] = {}
    total_counts: dict[UUID, int] = {}
    if product_ids:
        # total units regardless of status
        total_stmt = (
            select(InventoryUnit.product_id, func.count(InventoryUnit.id))
            .where(InventoryUnit.product_id.in_(product_ids))
            .group_by(InventoryUnit.product_id)
        )
        for pid, cnt in (await db.execute(total_stmt)).all():
            total_counts[pid] = int(cnt)
        # free units: AVAILABLE and not yet placed in any cell — these are the
        # ones that would be reused on placement.
        free_stmt = (
            select(InventoryUnit.product_id, func.count(InventoryUnit.id))
            .where(
                InventoryUnit.product_id.in_(product_ids),
                InventoryUnit.status == InventoryStatus.AVAILABLE,
                InventoryUnit.locker_cell_id.is_(None),
            )
            .group_by(InventoryUnit.product_id)
        )
        for pid, cnt in (await db.execute(free_stmt)).all():
            available_counts[pid] = int(cnt)

    cover_ids = [p.cover_file_id for p in products if p.cover_file_id]
    media_map = await load_media_files_by_ids(db, cover_ids) if cover_ids else {}

    items = []
    for product in products:
        cover_url = None
        if product.cover_file_id and product.cover_file_id in media_map:
            cover_url = public_media_url(media_map[product.cover_file_id].file_key)
        items.append(
            _serialize_product_row(
                product,
                cat_by_id.get(product.category_id),
                available_counts.get(product.id, 0),
                total_counts.get(product.id, 0),
                cover_url,
            )
        )

    return {
        "data": {"products": items},
        "meta": {"page": page, "limit": limit, "total": int(total)},
    }


def _map_esi_open_error(code: str) -> HTTPException:
    status_code, detail = _OPEN_ERR.get(code, (500, "Ошибка постамата"))
    return HTTPException(status_code=status_code, detail=detail)


@router.post("/cells/{cell_id}/place")
async def place_product_in_cell(
    request: Request,
    cell_id: UUID,
    payload: AdminPlaceProductInCellPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    cell = await db.get(LockerCell, cell_id)
    if cell is None:
        raise HTTPException(status_code=404, detail="Ячейка не найдена")
    locker = await db.get(LockerLocation, cell.locker_id)
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    if cell.status in (LockerCellStatus.FAULT, LockerCellStatus.DISABLED):
        raise HTTPException(
            status_code=409, detail="Ячейка не работает, выберите другую"
        )

    existing_in_cell = (
        await db.execute(
            select(InventoryUnit).where(InventoryUnit.locker_cell_id == cell.id)
        )
    ).scalar_one_or_none()
    if existing_in_cell is not None or cell.status == LockerCellStatus.OCCUPIED:
        raise HTTPException(status_code=409, detail="Ячейка уже занята")
    if cell.status == LockerCellStatus.RESERVED:
        raise HTTPException(
            status_code=409, detail="Ячейка зарезервирована под аренду"
        )

    product = await db.get(Product, payload.productId)
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден")

    # Reuse a free unit when possible, otherwise create a new one.
    free_unit = (
        await db.execute(
            select(InventoryUnit)
            .where(
                InventoryUnit.product_id == product.id,
                InventoryUnit.status == InventoryStatus.AVAILABLE,
                InventoryUnit.locker_cell_id.is_(None),
            )
            .order_by(InventoryUnit.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    created_new = False
    if free_unit is None:
        free_unit = InventoryUnit(
            product_id=product.id,
            status=InventoryStatus.AVAILABLE,
        )
        db.add(free_unit)
        await db.flush()
        created_new = True

    prev_status = free_unit.status

    open_failed_reason: str | None = None
    try:
        await sync_cell_state(
            db,
            locker_id=locker.id,
            cell_id=cell.id,
            state="occupied",
            pin=None,
        )
    except EsiOpenError as exc:
        code = str(exc)
        if code not in ("ESI_NOT_CONFIGURED", "ESI_MACHINE_OFFLINE", "ESI_HTTP_ERROR"):
            await db.rollback()
            raise _map_esi_open_error(code) from exc
        open_failed_reason = open_failed_reason or code

    if payload.openCell:
        try:
            await admin_trigger_open_cell(db, locker_id=locker.id, cell_id=cell.id)
        except EsiOpenError as exc:
            code = str(exc)
            if code not in ("ESI_NOT_CONFIGURED", "ESI_MACHINE_OFFLINE", "ESI_HTTP_ERROR"):
                await db.rollback()
                raise _map_esi_open_error(code) from exc
            open_failed_reason = code

    free_unit.locker_cell_id = cell.id
    free_unit.status = InventoryStatus.AVAILABLE
    cell.status = LockerCellStatus.OCCUPIED

    add_inventory_movement(
        db,
        unit=free_unit,
        from_locker_id=None,
        to_locker_id=locker.id,
        from_cell_id=None,
        to_cell_id=cell.id,
        from_status=prev_status,
        to_status=InventoryStatus.AVAILABLE,
        reason="admin_place_in_cell",
        comment=payload.comment,
        performed_by_admin_id=admin.id,
    )
    record_admin_audit(
        db,
        admin_account_id=admin.id,
        action="inventory.place",
        request=request,
        resource_type="locker_cell",
        resource_id=cell.id,
        payload={
            "lockerId": str(locker.id),
            "productId": str(product.id),
            "inventoryUnitId": str(free_unit.id),
            "createdNewUnit": created_new,
        },
    )

    try:
        await db.commit()
    except Exception as exc:
        import logging
        logging.error("Commit failed in place_product_in_cell: %s", exc, exc_info=exc)
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить размещение: {repr(exc)}") from exc

    await db.refresh(free_unit)
    await db.refresh(cell)

    cover_url = None
    if product.cover_file_id:
        media_map = await load_media_files_by_ids(db, [product.cover_file_id])
        m = media_map.get(product.cover_file_id)
        if m:
            cover_url = public_media_url(m.file_key)

    return {
        "data": {
            "cell": _serialize_cell_with_unit(cell, free_unit, product, cover_url),
            "createdNewUnit": created_new,
        }
    }


@router.post("/cells/{cell_id}/take-for-service")
async def take_cell_for_service(
    request: Request,
    cell_id: UUID,
    payload: AdminTakeForServicePayload = Body(default_factory=AdminTakeForServicePayload),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    cell = await db.get(LockerCell, cell_id)
    if cell is None:
        raise HTTPException(status_code=404, detail="Ячейка не найдена")
    locker = await db.get(LockerLocation, cell.locker_id)
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    unit = (
        await db.execute(
            select(InventoryUnit).where(InventoryUnit.locker_cell_id == cell.id)
        )
    ).scalar_one_or_none()
    if unit is None:
        raise HTTPException(status_code=404, detail="В ячейке нет товара")

    if unit.status not in (
        InventoryStatus.AVAILABLE,
        InventoryStatus.RETURN_PENDING,
        InventoryStatus.AWAITING_CONFIRMATION,
        InventoryStatus.MAINTENANCE,
        InventoryStatus.DAMAGED,
    ):
        raise HTTPException(
            status_code=409,
            detail="Товар сейчас участвует в аренде, изъятие невозможно",
        )

    target_status = (
        InventoryStatus.DAMAGED
        if payload.targetStatus == "damaged"
        else InventoryStatus.MAINTENANCE
    )

    open_failed_reason: str | None = None
    if payload.openCell:
        try:
            await admin_trigger_open_cell(db, locker_id=locker.id, cell_id=cell.id)
        except EsiOpenError as exc:
            code = str(exc)
            if code not in ("ESI_NOT_CONFIGURED", "ESI_MACHINE_OFFLINE", "ESI_HTTP_ERROR"):
                await db.rollback()
                raise _map_esi_open_error(code) from exc
            open_failed_reason = code

    try:
        await sync_cell_state(
            db,
            locker_id=locker.id,
            cell_id=cell.id,
            state="vacant",
            pin=None,
        )
    except EsiOpenError as exc:
        code = str(exc)
        if code not in ("ESI_NOT_CONFIGURED", "ESI_MACHINE_OFFLINE", "ESI_HTTP_ERROR"):
            await db.rollback()
            raise _map_esi_open_error(code) from exc
        open_failed_reason = open_failed_reason or code

    prev_status = unit.status
    unit.locker_cell_id = None
    unit.status = target_status
    cell.status = LockerCellStatus.VACANT

    add_inventory_movement(
        db,
        unit=unit,
        from_locker_id=locker.id,
        to_locker_id=None,
        from_cell_id=cell.id,
        to_cell_id=None,
        from_status=prev_status,
        to_status=target_status,
        reason="admin_take_for_service",
        comment=payload.reason,
        performed_by_admin_id=admin.id,
    )
    record_admin_audit(
        db,
        admin_account_id=admin.id,
        action="inventory.take_for_service",
        request=request,
        resource_type="locker_cell",
        resource_id=cell.id,
        payload={
            "lockerId": str(locker.id),
            "inventoryUnitId": str(unit.id),
            "targetStatus": target_status.value,
            "openCell": payload.openCell,
            "esiNote": open_failed_reason,
        },
    )

    try:
        await db.commit()
    except Exception as exc:
        import traceback; traceback.print_exc()
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить изменение: {repr(exc)}") from exc

    await db.refresh(cell)
    await db.refresh(unit)

    return {
        "data": {
            "cell": _serialize_cell_with_unit(cell, None, None, None),
            "removedUnit": {
                "id": str(unit.id),
                "status": unit.status.value,
                "productId": str(unit.product_id),
            },
            "esiNote": open_failed_reason,
        }
    }


@router.post("/confirm-ready")
async def confirm_inventory_ready(
    request: Request,
    payload: AdminConfirmInventoryReadyPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    unit: InventoryUnit | None = None
    cell: LockerCell | None = None

    if payload.inventoryUnitId is not None:
        unit = await db.get(InventoryUnit, payload.inventoryUnitId)
        if unit is None:
            raise HTTPException(status_code=404, detail="Товар не найден")
        if unit.locker_cell_id is not None:
            cell = await db.get(LockerCell, unit.locker_cell_id)
    elif payload.cellId is not None:
        cell = await db.get(LockerCell, payload.cellId)
        if cell is None:
            raise HTTPException(status_code=404, detail="Ячейка не найдена")
        unit = (
            await db.execute(select(InventoryUnit).where(InventoryUnit.locker_cell_id == cell.id))
        ).scalar_one_or_none()

    if unit is None:
        raise HTTPException(status_code=404, detail="В ячейке нет товара")
    if cell is None:
        raise HTTPException(status_code=409, detail="Товар не привязан к ячейке")
    if unit.status != InventoryStatus.AWAITING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="INVENTORY_UNIT_NOT_AWAITING_CONFIRMATION")

    locker = await db.get(LockerLocation, cell.locker_id)
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    product = await db.get(Product, unit.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден")

    now = datetime.now(timezone.utc)
    prev_status = unit.status
    unit.status = InventoryStatus.AVAILABLE
    unit.last_check_at = now

    add_inventory_movement(
        db,
        unit=unit,
        from_locker_id=locker.id,
        to_locker_id=locker.id,
        from_cell_id=cell.id,
        to_cell_id=cell.id,
        from_status=prev_status,
        to_status=InventoryStatus.AVAILABLE,
        reason="admin_confirm_ready",
        comment=payload.comment,
        performed_by_admin_id=admin.id,
    )

    # Auto-complete any active/unfinished rentals for this unit
    active_rentals = (
        await db.execute(
            select(Rental).where(
                Rental.inventory_unit_id == unit.id,
                Rental.status.notin_([RentalStatus.COMPLETED, RentalStatus.CANCELLED])
            )
        )
    ).scalars().all()

    for rental in active_rentals:
        prev_rental_status = rental.status
        rental.status = RentalStatus.COMPLETED
        rental.actual_end_at = now
        rental.completed_at = now
        db.add(
            RentalEvent(
                rental_id=rental.id,
                event_type="rental_completed_by_admin_confirm_ready",
                from_status=prev_rental_status,
                to_status=RentalStatus.COMPLETED,
                source=RentalEventSource.ADMIN,
                payload_json={
                    "admin_id": str(admin.id),
                    "comment": payload.comment,
                },
            )
        )
    record_admin_audit(
        db,
        admin_account_id=admin.id,
        action="inventory.confirm_ready",
        request=request,
        resource_type="inventory_unit",
        resource_id=unit.id,
        payload={
            "lockerId": str(locker.id),
            "cellId": str(cell.id),
            "inventoryUnitId": str(unit.id),
            "comment": payload.comment,
        },
    )

    try:
        await db.commit()
    except Exception as exc:
        import traceback; traceback.print_exc()
        with open("bug_error.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"INVENTORY_CONFIRM_READY_FAILED: {repr(exc)}") from exc

    await db.refresh(unit)
    await db.refresh(cell)

    cover_url = None
    if product.cover_file_id:
        media_map = await load_media_files_by_ids(db, [product.cover_file_id])
        media = media_map.get(product.cover_file_id)
        if media:
            cover_url = public_media_url(media.file_key)

    return {
        "data": {
            "cell": _serialize_cell_with_unit(cell, unit, product, cover_url),
            "confirmedUnit": {
                "id": str(unit.id),
                "status": unit.status.value,
                "lastCheckAt": unit.last_check_at.isoformat() if unit.last_check_at else None,
            },
        }
    }


def _read_cell_snapshot(machine: dict | None, external_cell_id: str) -> dict | None:
    if not isinstance(machine, dict):
        return None
    cells = machine.get("cells")
    if not isinstance(cells, dict):
        return None
    raw = cells.get(external_cell_id)
    if isinstance(raw, dict):
        return raw
    # ESI sometimes keys cells by integer-like strings; try a loose match.
    for key, value in cells.items():
        if str(key) == str(external_cell_id) and isinstance(value, dict):
            return value
    return None


@router.post("/cells/{cell_id}/test-open")
async def test_open_cell(
    request: Request,
    cell_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Тест открытия ячейки: отправляет ESI команду открытия и проверяет
    через `/machine/{serial}`, действительно ли ячейка открылась.
    Не меняет инвентарь и статусы — только аудит-запись.
    """
    admin, _ = await get_current_admin(request, db)

    cell = await db.get(LockerCell, cell_id)
    if cell is None:
        raise HTTPException(status_code=404, detail="Ячейка не найдена")
    locker = await db.get(LockerLocation, cell.locker_id)
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    serial = (locker.external_locker_id or "").strip()
    external_cell_id = (cell.external_cell_id or "").strip()
    if not serial or not external_cell_id:
        raise HTTPException(
            status_code=400,
            detail="У постамата или ячейки не указан внешний ID — открытие невозможно",
        )

    cell_label = cell.label or external_cell_id

    # 1) read state before
    before_machine: dict | None = None
    before_cell: dict | None = None
    before_error: str | None = None
    try:
        before_machine = await fetch_machine_snapshot(serial)
        before_cell = _read_cell_snapshot(before_machine, external_cell_id)
    except EsiDiscoveryError as exc:
        before_error = str(exc)

    # Игнорируем флаг 'online' в ESI, так как он может быть недостоверным.
    # Если ESI вернул снапшот, считаем точку доступной для попытки открытия.
    online_before = True if isinstance(before_machine, dict) else None
    open_before = bool(before_cell.get("open")) if isinstance(before_cell, dict) else None
    state_before = (
        str(before_cell.get("state") or "").strip().lower() if isinstance(before_cell, dict) else None
    )

    if online_before is False:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="inventory.test_open",
            request=request,
            resource_type="locker_cell",
            resource_id=cell.id,
            payload={
                "lockerId": str(locker.id),
                "serial": serial,
                "externalCellId": external_cell_id,
                "result": "machine_offline",
            },
        )
        await db.commit()
        return {
            "data": {
                "ok": False,
                "result": "machine_offline",
                "message": (
                    f"Постамат {serial} сейчас offline по данным ESI. "
                    "Открыть ячейку нельзя, пока постамат не выйдет в сеть."
                ),
                "cellLabel": cell_label,
                "serial": serial,
                "externalCellId": external_cell_id,
                "stateBefore": state_before,
                "openBefore": open_before,
            }
        }

    # 2) send open command
    open_started_at = time.monotonic()
    open_error: str | None = None
    try:
        await admin_trigger_open_cell(db, locker_id=locker.id, cell_id=cell.id)
    except EsiOpenError as exc:
        open_error = str(exc)

    if open_error is not None:
        if open_error == "ESI_MACHINE_OFFLINE":
            record_admin_audit(
                db,
                admin_account_id=admin.id,
                action="inventory.test_open",
                request=request,
                resource_type="locker_cell",
                resource_id=cell.id,
                payload={
                    "lockerId": str(locker.id),
                    "serial": serial,
                    "externalCellId": external_cell_id,
                    "result": "machine_offline",
                    "esiNote": "503 machine offline",
                },
            )
            await db.commit()
            return {
                "data": {
                    "ok": False,
                    "result": "machine_offline",
                    "message": (
                        f"Постамат {serial} сейчас offline по данным ESI. "
                        "Открыть ячейку нельзя, пока постамат не выйдет в сеть."
                    ),
                    "cellLabel": cell_label,
                    "serial": serial,
                    "externalCellId": external_cell_id,
                    "stateBefore": state_before,
                    "openBefore": open_before,
                }
            }

        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="inventory.test_open",
            request=request,
            resource_type="locker_cell",
            resource_id=cell.id,
            payload={
                "lockerId": str(locker.id),
                "serial": serial,
                "externalCellId": external_cell_id,
                "result": "open_failed",
                "esiError": open_error,
            },
        )
        await db.commit()
        return {
            "data": {
                "ok": False,
                "result": "open_failed",
                "message": (
                    f"ESI отклонил команду открытия ячейки {cell_label}: {open_error}."
                ),
                "cellLabel": cell_label,
                "serial": serial,
                "externalCellId": external_cell_id,
                "stateBefore": state_before,
                "openBefore": open_before,
            }
        }

    # 3) poll for open=true (max ~6s, every 600ms)
    poll_attempts = 0
    poll_max = 10
    poll_interval = 0.6
    open_after: bool | None = None
    state_after: str | None = state_before
    online_after: bool | None = True
    last_after_machine: dict | None = before_machine
    while poll_attempts < poll_max:
        poll_attempts += 1
        await asyncio.sleep(poll_interval)
        try:
            machine = await fetch_machine_snapshot(serial)
        except EsiDiscoveryError:
            continue
        if not isinstance(machine, dict):
            continue
        last_after_machine = machine
        # Игнорируем флаг 'online' в снапшоте после открытия ячейки.
        online_after = True
        cell_after = _read_cell_snapshot(machine, external_cell_id)
        if isinstance(cell_after, dict):
            open_after = bool(cell_after.get("open"))
            state_after = str(cell_after.get("state") or "").strip().lower() or None
            if open_after:
                break
    duration_ms = int((time.monotonic() - open_started_at) * 1000)

    if open_after is True:
        result = "opened"
        message = f"Ячейка {cell_label} физически открылась за {duration_ms} мс."
        ok = True
    elif open_after is False:
        result = "not_opened"
        message = (
            f"Команда открытия принята, но ESI всё ещё показывает ячейку {cell_label} закрытой "
            f"через {duration_ms} мс. Возможно, проблема с замком или связью с постаматом."
        )
        ok = False
    else:
        result = "no_state"
        message = (
            f"ESI не вернул информацию о ячейке {cell_label} после команды открытия. "
            "Проверьте внешний ID ячейки."
        )
        ok = False

    record_admin_audit(
        db,
        admin_account_id=admin.id,
        action="inventory.test_open",
        request=request,
        resource_type="locker_cell",
        resource_id=cell.id,
        payload={
            "lockerId": str(locker.id),
            "serial": serial,
            "externalCellId": external_cell_id,
            "result": result,
            "durationMs": duration_ms,
            "stateBefore": state_before,
            "openBefore": open_before,
            "stateAfter": state_after,
            "openAfter": open_after,
            "pollAttempts": poll_attempts,
            "discoveryError": before_error,
        },
    )
    await db.commit()

    return {
        "data": {
            "ok": ok,
            "result": result,
            "message": message,
            "cellLabel": cell_label,
            "serial": serial,
            "externalCellId": external_cell_id,
            "stateBefore": state_before,
            "openBefore": open_before,
            "stateAfter": state_after,
            "openAfter": open_after,
            "onlineAfter": online_after,
            "durationMs": duration_ms,
            "pollAttempts": poll_attempts,
        }
    }
