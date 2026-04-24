from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.enums import InventoryStatus
from backend.models.inventory_movement import InventoryMovement
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.reservation import Reservation
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.routers.admin.auth import get_current_admin
from backend.schemas.admin_panel_schemas import (
    AdminCreateLockerCellPayload,
    AdminCreateLockerPayload,
    AdminOpenCellPayload,
    AdminUpdateLockerCellPayload,
    AdminUpdateLockerPayload,
)
from backend.utils.admin_audit import record_admin_audit
from backend.utils.esi_client import (
    EsiDiscoveryError,
    EsiOpenError,
    admin_trigger_open_cell,
    discover_external_lockers,
)
from backend.utils.lockers_utils import (
    aggregate_available_inventory_by_product,
    build_locker_product_summaries,
    fetch_min_price_plans_by_product,
    load_locker_availability_counts,
    load_products_by_ids,
    serialize_locker_location,
)

router = APIRouter(prefix="/api/admin/lockers", tags=["admin-lockers"])

_OPEN_ERR = {
    "CELL_NOT_FOUND": (404, "Ячейка не найдена"),
    "CELL_NOT_OPERABLE": (409, "Ячейка недоступна для открытия"),
    "ESI_NOT_CONFIGURED": (503, "Интеграция с постаматом не настроена"),
    "ESI_HTTP_ERROR": (502, "Ошибка связи с постаматом"),
    "ESI_OPEN_FAILED": (502, "Постамат отклонил команду открытия"),
}

_DISCOVERY_ERR = {
    "ESI_DISCOVERY_HTTP_ERROR": (502, "Не удалось связаться с API постаматов"),
    "ESI_DISCOVERY_FAILED": (502, "API постаматов не вернул список точек"),
}


def serialize_admin_locker(
    locker: LockerLocation,
    city_name: str | None,
    available_product_count: int,
    available_unit_count: int,
) -> dict:
    payload = serialize_locker_location(
        locker,
        available_product_count=available_product_count,
        available_unit_count=available_unit_count,
    )
    payload["cityName"] = city_name
    payload["createdAt"] = locker.created_at.isoformat()
    payload["partnerName"] = locker.partner_name
    payload["externalLockerId"] = locker.external_locker_id
    payload["externalProvider"] = locker.external_provider
    payload["lastOnlineAt"] = locker.last_online_at.isoformat() if locker.last_online_at else None
    return payload


async def _ensure_no_external_duplicate(
    db: AsyncSession,
    *,
    external_provider: str | None,
    external_locker_id: str | None,
    exclude_locker_id: UUID | None = None,
):
    if not external_locker_id:
        return

    stmt = select(LockerLocation).where(
        LockerLocation.external_locker_id == external_locker_id
    )

    if external_provider:
        stmt = stmt.where(
            or_(
                LockerLocation.external_provider == external_provider,
                LockerLocation.external_provider.is_(None),
            )
        )

    if exclude_locker_id is not None:
        stmt = stmt.where(LockerLocation.id != exclude_locker_id)

    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Постамат с таким внешним ID уже добавлен",
        )


def _serialize_inventory_unit(unit: InventoryUnit | None, product: Product | None) -> dict | None:
    if unit is None:
        return None
    return {
        "id": str(unit.id),
        "status": unit.status.value,
        "serialNumber": unit.serial_number,
        "productId": str(unit.product_id),
        "productName": product.name if product else "",
    }


def _serialize_cell(cell: LockerCell, unit: InventoryUnit | None, product: Product | None) -> dict:
    return {
        "id": str(cell.id),
        "label": cell.label,
        "externalCellId": cell.external_cell_id,
        "size": cell.size,
        "status": cell.status.value,
        "supportsReturn": cell.supports_return,
        "lastOpenedAt": cell.last_opened_at.isoformat() if cell.last_opened_at else None,
        "lastClosedAt": cell.last_closed_at.isoformat() if cell.last_closed_at else None,
        "lastEventAt": cell.last_event_at.isoformat() if cell.last_event_at else None,
        "inventoryUnit": _serialize_inventory_unit(unit, product),
    }


def _serialize_rental_event_row(ev: RentalEvent) -> dict:
    return {
        "id": str(ev.id),
        "rentalId": str(ev.rental_id),
        "eventType": ev.event_type,
        "fromStatus": ev.from_status.value if ev.from_status else None,
        "toStatus": ev.to_status.value if ev.to_status else None,
        "source": ev.source.value,
        "createdAt": ev.created_at.isoformat(),
        "payload": ev.payload_json,
    }


@router.get("")
async def list_admin_lockers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    lockers = (
        await db.scalars(
            select(LockerLocation).order_by(LockerLocation.created_at.desc())
        )
    ).all()
    locker_ids = [locker.id for locker in lockers]
    counts = await load_locker_availability_counts(db, locker_ids)

    city_ids = [locker.city_id for locker in lockers]
    city_map: dict = {}
    if city_ids:
        cities = (await db.scalars(select(City).where(City.id.in_(city_ids)))).all()
        city_map = {city.id: city.name for city in cities}

    return {
        "data": {
            "lockers": [
                serialize_admin_locker(
                    locker,
                    city_name=city_map.get(locker.city_id),
                    available_product_count=counts.get(locker.id, (0, 0))[0],
                    available_unit_count=counts.get(locker.id, (0, 0))[1],
                )
                for locker in lockers
            ]
        },
        "meta": {"total": len(lockers)},
    }


@router.get("/external-candidates")
async def list_external_locker_candidates(
    request: Request,
    cityId: UUID | None = Query(default=None, description="Local city id"),
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    city_name = None
    if cityId is not None:
        city = await db.get(City, cityId)
        if city is None:
            raise HTTPException(status_code=404, detail="Город не найден")
        city_name = city.name

    try:
        items = await discover_external_lockers(db, city_name=city_name)
    except EsiDiscoveryError as exc:
        code = str(exc)
        mapped = _DISCOVERY_ERR.get(code, (500, "Не удалось получить список постаматов"))
        raise HTTPException(status_code=mapped[0], detail=mapped[1]) from exc

    return {"data": {"items": items}, "meta": {"total": len(items)}}


@router.post("")
async def create_admin_locker(
    request: Request,
    payload: AdminCreateLockerPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    city = await db.get(City, payload.cityId)
    if city is None:
        raise HTTPException(status_code=404, detail="Город не найден")

    normalized_name = payload.name.strip()
    normalized_address = payload.address.strip()
    partner_name = payload.partnerName.strip() if payload.partnerName else None
    external_locker_id = (
        payload.externalLockerId.strip() if payload.externalLockerId else None
    )
    external_provider = (
        payload.externalProvider.strip() if payload.externalProvider else None
    )

    if not normalized_name:
        raise HTTPException(status_code=422, detail="Название постамата обязательно")
    if not normalized_address:
        raise HTTPException(status_code=422, detail="Адрес постамата обязателен")

    await _ensure_no_external_duplicate(
        db,
        external_provider=external_provider,
        external_locker_id=external_locker_id,
    )

    lat_dec = Decimal(str(payload.lat)).quantize(Decimal("0.000001")) if payload.lat is not None else None
    lon_dec = Decimal(str(payload.lon)).quantize(Decimal("0.000001")) if payload.lon is not None else None

    locker = LockerLocation(
        city_id=city.id,
        name=normalized_name,
        address=normalized_address,
        status=payload.status,
        partner_name=partner_name or None,
        external_locker_id=external_locker_id or None,
        external_provider=external_provider or None,
        lat=lat_dec,
        lon=lon_dec,
        working_hours_json=payload.workingHours,
    )
    db.add(locker)

    try:
        await db.flush()
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="locker.create",
            request=request,
            resource_type="locker",
            resource_id=locker.id,
            payload={"name": locker.name},
        )
        await db.commit()
        await db.refresh(locker)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось создать постамат") from exc

    return {
        "data": {
            "locker": serialize_admin_locker(
                locker,
                city_name=city.name,
                available_product_count=0,
                available_unit_count=0,
            )
        }
    }


@router.post("/{locker_id}/open-cell")
async def admin_open_cell(
    request: Request,
    locker_id: UUID,
    payload: AdminOpenCellPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    locker = (
        await db.execute(select(LockerLocation).where(LockerLocation.id == locker_id))
    ).scalar_one_or_none()
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    try:
        await admin_trigger_open_cell(db, locker_id=locker_id, cell_id=payload.cellId)
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="locker.open_cell",
            request=request,
            resource_type="locker",
            resource_id=locker_id,
            payload={"cellId": str(payload.cellId), "note": payload.note},
        )
        await db.commit()
    except EsiOpenError as exc:
        await db.rollback()
        code = str(exc)
        mapped = _OPEN_ERR.get(code, (500, "Не удалось открыть ячейку"))
        raise HTTPException(status_code=mapped[0], detail=mapped[1]) from exc
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось открыть ячейку") from exc

    return {"data": {"message": "Команда открытия отправлена", "note": payload.note}}


@router.post("/{locker_id}/cells")
async def admin_create_locker_cell(
    request: Request,
    locker_id: UUID,
    payload: AdminCreateLockerCellPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    locker = (
        await db.execute(select(LockerLocation).where(LockerLocation.id == locker_id))
    ).scalar_one_or_none()
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    label = payload.label.strip() if payload.label else None
    ext = payload.externalCellId.strip() if payload.externalCellId else None
    size = payload.size.strip() if payload.size else None

    cell = LockerCell(
        locker_id=locker.id,
        label=label or None,
        external_cell_id=ext or None,
        size=size or None,
        supports_return=payload.supportsReturn,
    )
    db.add(cell)
    try:
        await db.flush()
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="locker.cell.create",
            request=request,
            resource_type="locker_cell",
            resource_id=cell.id,
            payload={"lockerId": str(locker_id)},
        )
        await db.commit()
        await db.refresh(cell)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось создать ячейку") from exc

    return {"data": {"cell": _serialize_cell(cell, None, None)}}


@router.patch("/{locker_id}/cells/{cell_id}")
async def admin_update_locker_cell(
    request: Request,
    locker_id: UUID,
    cell_id: UUID,
    payload: AdminUpdateLockerCellPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    cell = (
        await db.execute(
            select(LockerCell).where(LockerCell.id == cell_id, LockerCell.locker_id == locker_id)
        )
    ).scalar_one_or_none()
    if cell is None:
        raise HTTPException(status_code=404, detail="Ячейка не найдена")

    data = payload.model_dump(exclude_unset=True)
    if "label" in data and data["label"] is not None:
        cell.label = data["label"].strip() or None
    if "externalCellId" in data and data["externalCellId"] is not None:
        cell.external_cell_id = data["externalCellId"].strip() or None
    if "size" in data and data["size"] is not None:
        cell.size = data["size"].strip() or None
    if "status" in data:
        cell.status = data["status"]
    if "supportsReturn" in data and data["supportsReturn"] is not None:
        cell.supports_return = data["supportsReturn"]

    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="locker.cell.update",
            request=request,
            resource_type="locker_cell",
            resource_id=cell_id,
            payload={"lockerId": str(locker_id), "fields": list(data.keys())},
        )
        await db.commit()
        await db.refresh(cell)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось обновить ячейку") from exc

    unit = (
        await db.execute(select(InventoryUnit).where(InventoryUnit.locker_cell_id == cell.id))
    ).scalar_one_or_none()
    product = await db.get(Product, unit.product_id) if unit else None

    return {"data": {"cell": _serialize_cell(cell, unit, product)}}


@router.get("/{locker_id}")
async def get_admin_locker(
    request: Request,
    locker_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    locker = (
        await db.execute(select(LockerLocation).where(LockerLocation.id == locker_id))
    ).scalar_one_or_none()
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    city = await db.get(City, locker.city_id)
    city_name = city.name if city else None

    counts = await load_locker_availability_counts(db, [locker.id])
    avail_p, avail_u = counts.get(locker.id, (0, 0))

    cells = (
        await db.scalars(
            select(LockerCell)
            .where(LockerCell.locker_id == locker_id)
            .order_by(LockerCell.label.asc().nulls_last(), LockerCell.created_at.asc())
        )
    ).all()

    cell_ids = [c.id for c in cells]
    units_by_cell: dict[UUID, InventoryUnit] = {}
    if cell_ids:
        units = (
            await db.scalars(select(InventoryUnit).where(InventoryUnit.locker_cell_id.in_(cell_ids)))
        ).all()
        units_by_cell = {u.locker_cell_id: u for u in units if u.locker_cell_id}

    product_counts = await aggregate_available_inventory_by_product(db, locker_id, None)
    product_ids_units = {u.product_id for u in units_by_cell.values()}
    all_product_ids = list(product_ids_units | set(product_counts.keys()))
    products = await load_products_by_ids(db, all_product_ids)

    cells_payload = [
        _serialize_cell(
            c,
            units_by_cell.get(c.id),
            products.get(units_by_cell[c.id].product_id) if units_by_cell.get(c.id) else None,
        )
        for c in cells
    ]

    plans = await fetch_min_price_plans_by_product(db, list(product_counts.keys()))
    product_summaries = build_locker_product_summaries(product_counts, products, plans)

    events_stmt = (
        select(RentalEvent)
        .join(Rental, RentalEvent.rental_id == Rental.id)
        .where(
            or_(
                Rental.pickup_locker_id == locker_id,
                Rental.return_locker_id == locker_id,
            )
        )
        .order_by(RentalEvent.created_at.desc())
        .limit(30)
    )
    events = (await db.scalars(events_stmt)).all()

    locker_payload = serialize_admin_locker(
        locker,
        city_name=city_name,
        available_product_count=avail_p,
        available_unit_count=avail_u,
    )
    locker_payload["updatedAt"] = locker.updated_at.isoformat()

    return {
        "data": {
            "locker": locker_payload,
            "cells": cells_payload,
            "productSummaries": product_summaries,
            "recentEvents": [_serialize_rental_event_row(ev) for ev in events],
        }
    }


@router.patch("/{locker_id}")
async def update_admin_locker(
    request: Request,
    locker_id: UUID,
    payload: AdminUpdateLockerPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    locker = (
        await db.execute(select(LockerLocation).where(LockerLocation.id == locker_id))
    ).scalar_one_or_none()
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    data = payload.model_dump(exclude_unset=True)

    if "cityId" in data:
        city = await db.get(City, data["cityId"])
        if city is None:
            raise HTTPException(status_code=404, detail="Город не найден")
        locker.city_id = city.id

    if "name" in data and data["name"] is not None:
        name = data["name"].strip()
        if not name:
            raise HTTPException(status_code=422, detail="Название не может быть пустым")
        locker.name = name

    if "address" in data and data["address"] is not None:
        addr = data["address"].strip()
        if not addr:
            raise HTTPException(status_code=422, detail="Адрес не может быть пустым")
        locker.address = addr

    if "status" in data:
        locker.status = data["status"]

    if "partnerName" in data:
        pn = data["partnerName"]
        locker.partner_name = pn.strip() if isinstance(pn, str) and pn.strip() else None

    if "externalLockerId" in data:
        eid = data["externalLockerId"]
        locker.external_locker_id = eid.strip() if isinstance(eid, str) and eid.strip() else None

    if "externalProvider" in data:
        ep = data["externalProvider"]
        locker.external_provider = ep.strip() if isinstance(ep, str) and ep.strip() else None

    await _ensure_no_external_duplicate(
        db,
        external_provider=locker.external_provider,
        external_locker_id=locker.external_locker_id,
        exclude_locker_id=locker.id,
    )

    if "lat" in data:
        if data["lat"] is None:
            locker.lat = None
        else:
            locker.lat = Decimal(str(data["lat"])).quantize(Decimal("0.000001"))

    if "lon" in data:
        if data["lon"] is None:
            locker.lon = None
        else:
            locker.lon = Decimal(str(data["lon"])).quantize(Decimal("0.000001"))

    if "workingHours" in data:
        locker.working_hours_json = data["workingHours"]

    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="locker.update",
            request=request,
            resource_type="locker",
            resource_id=locker_id,
            payload={"fields": list(data.keys())},
        )
        await db.commit()
        await db.refresh(locker)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось обновить постамат") from exc

    city = await db.get(City, locker.city_id)
    counts = await load_locker_availability_counts(db, [locker.id])
    avail_p, avail_u = counts.get(locker.id, (0, 0))

    return {
        "data": {
            "locker": serialize_admin_locker(
                locker,
                city_name=city.name if city else None,
                available_product_count=avail_p,
                available_unit_count=avail_u,
            )
        }
    }


async def _perform_admin_locker_delete(
    request: Request,
    locker_id: UUID,
    db: AsyncSession,
) -> dict:
    admin, _ = await get_current_admin(request, db)

    locker = (
        await db.execute(select(LockerLocation).where(LockerLocation.id == locker_id))
    ).scalar_one_or_none()
    if locker is None:
        raise HTTPException(status_code=404, detail="Постамат не найден")

    res_count = await db.scalar(
        select(func.count()).select_from(Reservation).where(Reservation.locker_id == locker_id)
    )
    if res_count and int(res_count) > 0:
        raise HTTPException(
            status_code=409,
            detail="Нельзя удалить постамат: есть связанные бронирования.",
        )

    rent_count = await db.scalar(
        select(func.count())
        .select_from(Rental)
        .where(
            or_(
                Rental.pickup_locker_id == locker_id,
                Rental.return_locker_id == locker_id,
            )
        )
    )
    if rent_count and int(rent_count) > 0:
        raise HTTPException(
            status_code=409,
            detail="Нельзя удалить постамат: есть связанные аренды.",
        )

    mov_locker = await db.scalar(
        select(func.count())
        .select_from(InventoryMovement)
        .where(
            or_(
                InventoryMovement.from_locker_id == locker_id,
                InventoryMovement.to_locker_id == locker_id,
            )
        )
    )
    if mov_locker and int(mov_locker) > 0:
        raise HTTPException(
            status_code=409,
            detail="Нельзя удалить постамат: есть история движений инвентаря по этой точке.",
        )

    cells = (
        await db.scalars(select(LockerCell).where(LockerCell.locker_id == locker_id))
    ).all()
    cell_ids = [c.id for c in cells]

    if cell_ids:
        inv_count = await db.scalar(
            select(func.count())
            .select_from(InventoryUnit)
            .where(InventoryUnit.locker_cell_id.in_(cell_ids))
        )
        if inv_count and int(inv_count) > 0:
            raise HTTPException(
                status_code=409,
                detail="Сначала изымите все единицы инвентаря из ячеек постамата.",
            )

        mov_cell = await db.scalar(
            select(func.count())
            .select_from(InventoryMovement)
            .where(
                or_(
                    InventoryMovement.from_cell_id.in_(cell_ids),
                    InventoryMovement.to_cell_id.in_(cell_ids),
                )
            )
        )
        if mov_cell and int(mov_cell) > 0:
            raise HTTPException(
                status_code=409,
                detail="Нельзя удалить постамат: в истории есть операции с ячейками этой точки.",
            )

    try:
        locker_name = locker.name
        if cell_ids:
            await db.execute(delete(LockerCell).where(LockerCell.locker_id == locker_id))
        await db.delete(locker)
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="locker.delete",
            request=request,
            resource_type="locker",
            resource_id=locker_id,
            payload={"name": locker_name},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось удалить постамат") from exc

    return {"data": {"deleted": True, "lockerId": str(locker_id)}}


@router.delete("/{locker_id}")
async def delete_admin_locker(
    request: Request,
    locker_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await _perform_admin_locker_delete(request, locker_id, db)


@router.post("/{locker_id}/delete")
async def delete_admin_locker_post(
    request: Request,
    locker_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """То же, что DELETE: POST удобен, если прокси режет DELETE."""
    return await _perform_admin_locker_delete(request, locker_id, db)
