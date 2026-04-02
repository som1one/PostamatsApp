from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.enums import LockerStatus
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.utils.lockers_utils import (
    aggregate_available_inventory_by_product,
    fetch_min_price_plans_by_product,
    price_plan_to_minor_units,
)
from backend.utils.products_utils import (
    aggregate_available_in_city,
    find_price_plan,
    load_available_lockers_for_product,
    load_media_files_by_ids,
    load_price_plans_for_product,
    load_product_images_with_urls,
    public_media_url,
    serialize_product_list_item,
)

router = APIRouter(prefix="/products", tags=["products"])


def _parse_uuid_param(raw: str | None, error_code: str) -> UUID | None:
    if raw is None or raw == "":
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=error_code) from exc


@router.get("")
async def get_products(
    db: AsyncSession = Depends(get_db),
    cityId: str | None = Query(None),
    lockerId: str | None = Query(None),
    categoryId: str | None = Query(None),
    search: str | None = Query(None),
    availableOnly: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    city_uuid = _parse_uuid_param(cityId, "INVALID_CITY_ID")
    locker_uuid = _parse_uuid_param(lockerId, "INVALID_LOCKER_ID")
    category_uuid = _parse_uuid_param(categoryId, "INVALID_CATEGORY_ID")

    if city_uuid is not None:
        city = await db.get(City, city_uuid)
        if not city:
            raise HTTPException(status_code=404, detail="CITY_NOT_FOUND")

    locker: LockerLocation | None = None
    if locker_uuid is not None:
        locker = await db.get(LockerLocation, locker_uuid)
        if not locker:
            raise HTTPException(status_code=404, detail="LOCKER_NOT_FOUND")
        if city_uuid is not None and locker.city_id != city_uuid:
            raise HTTPException(status_code=400, detail="INVALID_FILTERS")

    if category_uuid is not None:
        category = await db.get(ProductCategory, category_uuid)
        if not category:
            raise HTTPException(status_code=404, detail="CATEGORY_NOT_FOUND")

    unit_counts: dict[UUID, int] = {}
    locker_counts: dict[UUID, int] = {}
    candidate_ids: set[UUID] | None = None

    try:
        if locker_uuid is not None:
            unit_counts = await aggregate_available_inventory_by_product(
                db, locker_uuid, None
            )
            locker_counts = {pid: 1 for pid in unit_counts if unit_counts[pid] > 0}
            candidate_ids = set(unit_counts.keys())
        elif city_uuid is not None:
            unit_counts, locker_counts = await aggregate_available_in_city(db, city_uuid)
            candidate_ids = set(unit_counts.keys())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PRODUCTS_FETCH_FAILED") from exc

    conditions = [Product.is_active.is_(True)]

    if candidate_ids is not None:
        if not candidate_ids:
            return {
                "data": {"products": []},
                "meta": {"page": page, "limit": limit, "total": 0},
            }
        conditions.append(Product.id.in_(candidate_ids))

    if category_uuid is not None:
        conditions.append(Product.category_id == category_uuid)

    if search:
        term = f"%{search.strip()}%"
        conditions.append(
            or_(Product.name.ilike(term), Product.slug.ilike(term)),
        )

    if availableOnly and candidate_ids is not None:
        in_stock = {pid for pid, n in unit_counts.items() if n > 0}
        if not in_stock:
            return {
                "data": {"products": []},
                "meta": {"page": page, "limit": limit, "total": 0},
            }
        conditions.append(Product.id.in_(in_stock))

    where_clause = and_(*conditions) if conditions else true()

    try:
        total_stmt = select(func.count()).select_from(Product).where(where_clause)
        total = (await db.execute(total_stmt)).scalar_one()

        list_stmt = (
            select(Product)
            .where(where_clause)
            .order_by(Product.name.asc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        rows = list((await db.scalars(list_stmt)).all())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PRODUCTS_FETCH_FAILED") from exc

    product_ids = [p.id for p in rows]
    plans = await fetch_min_price_plans_by_product(db, product_ids)
    cover_ids = [p.cover_file_id for p in rows if p.cover_file_id]
    media_map = await load_media_files_by_ids(db, [cid for cid in cover_ids if cid])

    products_payload: list[dict] = []
    for p in rows:
        plan = plans.get(p.id)
        cover_url = None
        if p.cover_file_id and p.cover_file_id in media_map:
            cover_url = public_media_url(media_map[p.cover_file_id].file_key)
        u = unit_counts.get(p.id, 0)
        lc = locker_counts.get(p.id, 0)
        if candidate_ids is None:
            u = 0
            lc = 0
        products_payload.append(
            serialize_product_list_item(
                p,
                plan,
                cover_url,
                available=u > 0,
                available_locker_count=lc,
                unit_count=u,
            )
        )

    return {
        "data": {"products": products_payload},
        "meta": {"page": page, "limit": limit, "total": total},
    }


@router.get("/{product_id}/pricing")
async def get_product_pricing(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    lockerId: str = Query(..., description="Pickup point UUID"),
    durationType: str = Query("day"),
    durationValue: int = Query(1, ge=1),
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    if not product.is_active:
        raise HTTPException(status_code=410, detail="PRODUCT_INACTIVE")

    locker_uuid = _parse_uuid_param(lockerId, "INVALID_LOCKER_ID")
    if locker_uuid is None:
        raise HTTPException(status_code=400, detail="INVALID_LOCKER_ID")

    locker = await db.get(LockerLocation, locker_uuid)
    if not locker:
        raise HTTPException(status_code=404, detail="LOCKER_NOT_FOUND")
    if locker.status != LockerStatus.ONLINE:
        raise HTTPException(status_code=409, detail="LOCKER_OFFLINE")

    plan = await find_price_plan(db, product_id, durationType, durationValue)
    if plan is None:
        raise HTTPException(status_code=404, detail="PRICE_PLAN_NOT_FOUND")

    try:
        counts = await aggregate_available_inventory_by_product(
            db, locker_uuid, product_id
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PRICING_FAILED") from exc

    units = counts.get(product_id, 0)
    if units <= 0:
        raise HTTPException(status_code=409, detail="PRODUCT_NOT_AVAILABLE")

    base = price_plan_to_minor_units(plan.base_amount, plan.currency)
    return {
        "data": {
            "productId": str(product_id),
            "lockerId": str(locker_uuid),
            "durationType": durationType,
            "durationValue": durationValue,
            "currency": plan.currency,
            "baseAmount": base,
            "discountAmount": 0,
            "depositAmount": 0,
            "preauthAmount": base,
            "totalAmount": base,
            "available": True,
        }
    }


@router.get("/{product_id}")
async def get_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    cityId: str | None = Query(None),
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    if not product.is_active:
        raise HTTPException(status_code=410, detail="PRODUCT_INACTIVE")

    city_uuid = _parse_uuid_param(cityId, "INVALID_CITY_ID")
    if city_uuid is not None:
        city = await db.get(City, city_uuid)
        if not city:
            raise HTTPException(status_code=404, detail="CITY_NOT_FOUND")

    try:
        plans = await load_price_plans_for_product(db, product_id)
        images = await load_product_images_with_urls(db, product_id)
        lockers = await load_available_lockers_for_product(db, product_id, city_uuid)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PRODUCT_FETCH_FAILED") from exc

    price_plans_out = [
        {
            "id": str(pl.id),
            "name": pl.name,
            "durationType": pl.duration_type,
            "durationValue": pl.duration_value,
            "baseAmount": price_plan_to_minor_units(pl.base_amount, pl.currency),
            "currency": pl.currency,
        }
        for pl in plans
    ]

    cover_url = None
    if product.cover_file_id:
        media_map = await load_media_files_by_ids(db, [product.cover_file_id])
        m = media_map.get(product.cover_file_id)
        if m:
            cover_url = public_media_url(m.file_key)

    return {
        "data": {
            "product": {
                "id": str(product.id),
                "categoryId": str(product.category_id),
                "name": product.name,
                "slug": product.slug,
                "shortDescription": product.short_description,
                "fullDescription": product.full_description,
                "brand": product.brand,
                "specs": product.specs_json,
                "rulesText": product.rules_text,
                "kitDescription": product.kit_description,
                "coverUrl": cover_url,
                "images": images,
                "pricePlans": price_plans_out,
                "availableLockers": lockers,
            }
        }
    }
