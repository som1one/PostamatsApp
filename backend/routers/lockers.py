from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import and_, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.enums import InventoryStatus, LockerStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.utils.lockers_utils import (
    LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY,
    aggregate_available_inventory_by_product,
    build_availability_items,
    build_locker_product_summaries,
    fetch_min_price_plans_by_product,
    load_locker_availability_counts,
    load_products_by_ids,
    serialize_locker_location,
)

router = APIRouter(prefix="/lockers", tags=["lockers"])


@router.get("/")
async def get_lockers(
    db: AsyncSession = Depends(get_db),
    cityId: str | None = Query(None, description="City UUID"),
    status: LockerStatus | None = Query(None),
    hasAvailableItems: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    city_uuid: UUID | None = None
    if cityId is not None:
        try:
            city_uuid = UUID(cityId)
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_CITY_ID")

    lockers_with_avail = (
        select(LockerCell.locker_id)
        .join(InventoryUnit, InventoryUnit.locker_cell_id == LockerCell.id)
        .where(
            InventoryUnit.status == InventoryStatus.AVAILABLE,
            LockerCell.status.not_in(LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY),
        )
        .distinct()
    )

    try:
        if city_uuid is not None:
            city = await db.get(City, city_uuid)
            if not city:
                raise HTTPException(status_code=404, detail="CITY_NOT_FOUND")

        conditions = []
        if city_uuid is not None:
            conditions.append(LockerLocation.city_id == city_uuid)
        if status is not None:
            conditions.append(LockerLocation.status == status)
        if hasAvailableItems is True:
            conditions.append(LockerLocation.id.in_(lockers_with_avail))
        elif hasAvailableItems is False:
            conditions.append(~LockerLocation.id.in_(lockers_with_avail))

        where_clause = and_(*conditions) if conditions else true()

        total_stmt = select(func.count(LockerLocation.id)).where(where_clause)
        total = (await db.execute(total_stmt)).scalar_one()

        list_stmt = (
            select(LockerLocation)
            .where(where_clause)
            .order_by(LockerLocation.name.asc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        locations = (await db.scalars(list_stmt)).all()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="LOCKERS_FETCH_FAILED")

    locker_ids = [loc.id for loc in locations]
    counts = await load_locker_availability_counts(db, locker_ids)
    lockers_payload = [
        serialize_locker_location(
            loc,
            counts.get(loc.id, (0, 0))[0],
            counts.get(loc.id, (0, 0))[1],
        )
        for loc in locations
    ]

    return {
        "data": {"lockers": lockers_payload},
        "meta": {"page": page, "limit": limit, "total": total},
    }


def _parse_locker_id(locker_id: str) -> UUID:
    try:
        return UUID(locker_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_LOCKER_ID")


@router.get("/{lockerId}")
async def get_locker(
    db: AsyncSession = Depends(get_db),
    lockerId: str = Path(..., description="Locker UUID"),
):
    try:
        lid = _parse_locker_id(lockerId)
        locker = await db.get(LockerLocation, lid)
        if not locker:
            raise HTTPException(status_code=404, detail="LOCKER_NOT_FOUND")

        counts = await load_locker_availability_counts(db, [locker.id])
        pc, uc = counts.get(locker.id, (0, 0))
        product_counts = await aggregate_available_inventory_by_product(db, locker.id, None)
        product_ids = list(product_counts.keys())
        products = await load_products_by_ids(db, product_ids)
        plans = await fetch_min_price_plans_by_product(db, product_ids)
        products_payload = build_locker_product_summaries(product_counts, products, plans)

        return {
            "data": {
                "locker": {
                    **serialize_locker_location(locker, pc, uc),
                    "products": products_payload,
                }
            },
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="LOCKER_FETCH_FAILED")


@router.get("/{lockerId}/availability")
async def get_locker_availability(
    db: AsyncSession = Depends(get_db),
    lockerId: str = Path(..., description="Locker UUID"),
    productId: str | None = Query(None, description="Filter by product UUID"),
):
    product_uuid: UUID | None = None
    if productId is not None:
        try:
            product_uuid = UUID(productId)
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_PRODUCT_ID")

    try:
        lid = _parse_locker_id(lockerId)
        locker = await db.get(LockerLocation, lid)
        if not locker:
            raise HTTPException(status_code=404, detail="LOCKER_NOT_FOUND")
        if locker.status != LockerStatus.ONLINE:
            raise HTTPException(status_code=409, detail="LOCKER_OFFLINE")

        product_counts = await aggregate_available_inventory_by_product(db, locker.id, product_uuid)
        product_ids = list(product_counts.keys())
        products = await load_products_by_ids(db, product_ids)
        plans = await fetch_min_price_plans_by_product(db, product_ids)
        items = build_availability_items(product_counts, products, plans)

        return {
            "data": {
                "lockerId": str(locker.id),
                "status": locker.status.value,
                "items": items,
            },
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="LOCKER_AVAILABILITY_FAILED")
