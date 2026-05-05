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
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_filter import ProductFilter
from backend.utils.lockers_utils import (
    LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY,
    aggregate_available_inventory_by_product,
    fetch_min_price_plans_by_product,
    load_locker_availability_counts,
    load_products_by_ids,
    price_plan_to_minor_units,
    serialize_locker_location,
)
from backend.utils.product_filters import (
    is_product_visible,
    load_product_filters_by_product_ids,
    normalize_filter_price_plans,
)

router = APIRouter(prefix="/lockers", tags=["lockers"])


def _build_effective_locker_product_summaries(
    product_counts: dict[UUID, int],
    products: dict[UUID, Product],
    plans: dict[UUID, PricePlan],
    filters_by_product_id: dict[UUID, ProductFilter],
) -> list[dict]:
    out: list[dict] = []
    for product_id, count in product_counts.items():
        if count <= 0:
            continue
        product = products.get(product_id)
        if product is None:
            continue
        product_filter = filters_by_product_id.get(product_id)
        if not is_product_visible(product, product_filter):
            continue

        name = (
            product_filter.name.strip()
            if product_filter and product_filter.name and product_filter.name.strip()
            else product.name
        )
        filter_plans = normalize_filter_price_plans(product_filter)
        min_plan = min(filter_plans, key=lambda item: int(item["baseAmount"])) if filter_plans else None
        price_from = (
            int(min_plan["baseAmount"])
            if min_plan is not None
            else (
                price_plan_to_minor_units(plans[product_id].base_amount, plans[product_id].currency)
                if product_id in plans
                else None
            )
        )
        out.append(
            {
                "productId": str(product_id),
                "name": name,
                "available": True,
                "priceFrom": price_from,
            }
        )
    return out


def _build_effective_availability_items(
    product_counts: dict[UUID, int],
    products: dict[UUID, Product],
    plans: dict[UUID, PricePlan],
    filters_by_product_id: dict[UUID, ProductFilter],
) -> list[dict]:
    items: list[dict] = []
    for product_id, available_units in product_counts.items():
        if available_units <= 0:
            continue
        product = products.get(product_id)
        if product is None:
            continue
        product_filter = filters_by_product_id.get(product_id)
        if not is_product_visible(product, product_filter):
            continue

        name = (
            product_filter.name.strip()
            if product_filter and product_filter.name and product_filter.name.strip()
            else product.name
        )
        filter_plans = normalize_filter_price_plans(product_filter)
        if filter_plans:
            min_plan = min(filter_plans, key=lambda item: int(item["baseAmount"]))
            items.append(
                {
                    "productId": str(product_id),
                    "productName": name,
                    "availableUnits": available_units,
                    "minDurationType": min_plan["durationType"],
                    "minDurationValue": int(min_plan["durationValue"]),
                    "priceFrom": int(min_plan["baseAmount"]),
                    "currency": min_plan["currency"],
                }
            )
            continue

        plan = plans.get(product_id)
        items.append(
            {
                "productId": str(product_id),
                "productName": name,
                "availableUnits": available_units,
                "minDurationType": plan.duration_type if plan else None,
                "minDurationValue": plan.duration_value if plan else None,
                "priceFrom": (
                    price_plan_to_minor_units(plan.base_amount, plan.currency) if plan else None
                ),
                "currency": plan.currency if plan else "RUB",
            }
        )
    return items


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
        filters_by_product_id = await load_product_filters_by_product_ids(db, product_ids)
        products_payload = _build_effective_locker_product_summaries(
            product_counts,
            products,
            plans,
            filters_by_product_id,
        )

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
        filters_by_product_id = await load_product_filters_by_product_ids(db, product_ids)
        items = _build_effective_availability_items(
            product_counts,
            products,
            plans,
            filters_by_product_id,
        )

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
