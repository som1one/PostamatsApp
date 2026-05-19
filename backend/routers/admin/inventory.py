from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.enums import InventoryStatus, LockerCellStatus, LockerStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.routers.admin.auth import get_current_admin
from backend.schemas.admin_panel_schemas import (
    AdminPlaceProductInCellPayload,
    AdminTakeForServicePayload,
)
from backend.utils.admin_audit import record_admin_audit
from backend.utils.esi_client import (
    EsiOpenError,
    admin_trigger_open_cell,
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
    try:
        await sync_cell_state(
            db,
            locker_id=locker.id,
            cell_id=cell.id,
            state="occupied",
            pin=None,
        )
    except EsiOpenError as exc:
        await db.rollback()
        raise _map_esi_open_error(str(exc)) from exc

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
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось сохранить размещение") from exc

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
            if code == "ESI_NOT_CONFIGURED":
                # Best-effort: continue without ESI when integration is not set up.
                open_failed_reason = "ESI_NOT_CONFIGURED"
            else:
                await db.rollback()
                raise _map_esi_open_error(code) from exc

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
        if code != "ESI_NOT_CONFIGURED":
            await db.rollback()
            raise _map_esi_open_error(code) from exc
        open_failed_reason = open_failed_reason or "ESI_NOT_CONFIGURED"

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
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось сохранить изменение") from exc

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
