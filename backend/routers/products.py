from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.enums import LockerStatus, ReservationStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.reservation import Reservation
from backend.utils.auth_utils import get_current_client_user
from backend.utils.featured_product import get_featured_product_state
from backend.utils.lockers_utils import (
    aggregate_available_inventory_by_product,
    fetch_min_price_plans_by_product,
    price_plan_to_minor_units,
)
from backend.utils.products_utils import (
    aggregate_available_globally,
    aggregate_available_in_city,
    aggregate_placed_at_locker,
    aggregate_placed_globally,
    aggregate_placed_in_city,
    compute_busy_dates_for_product,
    find_price_plan,
    load_available_lockers_for_product,
    load_media_files_by_ids,
    load_price_plans_for_product,
    load_product_images_with_urls,
    public_media_url,
    serialize_product_list_item,
)
from backend.utils.product_filters import (
    find_effective_filter_price_plan,
    is_product_visible,
    load_product_filter,
    load_product_filters_by_product_ids,
    resolve_effective_detail_item,
    resolve_effective_list_item,
    resolve_effective_price_plans,
    serialize_base_price_plan,
)

router = APIRouter(prefix="/products", tags=["products"])


async def _get_filter_only_product_ids(db: AsyncSession) -> set[UUID]:
    """Return product IDs that have an active product_filter and is_active=True,
    but no inventory placed in any locker cell. These are 'catalog-only' items
    shown as unavailable for rental."""
    from backend.models.product_filter import ProductFilter

    stmt = (
        select(ProductFilter.product_id)
        .join(Product, Product.id == ProductFilter.product_id)
        .where(
            ProductFilter.is_active.is_(True),
            Product.is_active.is_(True),
            ~Product.id.in_(
                select(InventoryUnit.product_id)
                .where(InventoryUnit.locker_cell_id.isnot(None))
                .distinct()
            ),
        )
    )
    return {row for row in (await db.scalars(stmt)).all()}


def _parse_uuid_param(raw: str | None, error_code: str) -> UUID | None:
    if raw is None or raw == "":
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=error_code) from exc


async def _load_reschedule_reservation(
    request: Request,
    db: AsyncSession,
    reservation_id: UUID | None,
    *,
    product_id: UUID | None = None,
    locker_id: UUID | None = None,
) -> Reservation | None:
    if reservation_id is None:
        return None

    user = await get_current_client_user(request, db)
    reservation = await db.get(Reservation, reservation_id)
    if reservation is None or reservation.user_id != user.id:
        raise HTTPException(status_code=404, detail="RESERVATION_NOT_FOUND")
    if reservation.status not in (
        ReservationStatus.CREATED,
        ReservationStatus.AWAITING_PAYMENT,
        ReservationStatus.PAYMENT_AUTHORIZED,
    ):
        return None
    if product_id is not None and reservation.product_id != product_id:
        return None
    if locker_id is not None and reservation.locker_id != locker_id:
        return None
    return reservation


async def _serialize_product_list_payload(
    db: AsyncSession,
    product: Product,
    product_filter,
    *,
    city_uuid: UUID | None = None,
    locker_uuid: UUID | None = None,
) -> dict:
    if locker_uuid is not None:
        unit_counts = await aggregate_available_inventory_by_product(db, locker_uuid, None)
        locker_counts = {pid: 1 for pid, count in unit_counts.items() if count > 0}
    elif city_uuid is not None:
        unit_counts, locker_counts = await aggregate_available_in_city(db, city_uuid)
    else:
        unit_counts, locker_counts = await aggregate_available_globally(db)

    plans = await fetch_min_price_plans_by_product(db, [product.id])
    media_map = await load_media_files_by_ids(
        db,
        [product.cover_file_id] if product.cover_file_id else [],
    )

    cover_url = None
    if product.cover_file_id:
        media = media_map.get(product.cover_file_id)
        if media:
            cover_url = public_media_url(media.file_key)

    if locker_uuid is not None:
        placed_ids = await aggregate_placed_at_locker(db, locker_uuid)
    elif city_uuid is not None:
        placed_ids = await aggregate_placed_in_city(db, city_uuid)
    else:
        placed_ids = await aggregate_placed_globally(db)

    unit_count = unit_counts.get(product.id, 0)
    locker_count = locker_counts.get(product.id, 0)
    is_in_stock = product.id in placed_ids
    payload = serialize_product_list_item(
        product,
        plans.get(product.id),
        cover_url,
        available=is_in_stock,
        available_locker_count=locker_count,
        unit_count=unit_count,
    )
    return resolve_effective_list_item(payload, product_filter)


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

    try:
        if locker_uuid is not None:
            unit_counts = await aggregate_available_inventory_by_product(
                db, locker_uuid, None
            )
            locker_counts = {pid: 1 for pid in unit_counts if unit_counts[pid] > 0}
        elif city_uuid is not None:
            unit_counts, locker_counts = await aggregate_available_in_city(db, city_uuid)
        else:
            unit_counts, locker_counts = await aggregate_available_globally(db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PRODUCTS_FETCH_FAILED") from exc

    conditions = [Product.is_active.is_(True)]

    if category_uuid is not None:
        conditions.append(Product.category_id == category_uuid)

    if search:
        term = f"%{search.strip()}%"
        conditions.append(
            or_(
                Product.name.ilike(term),
                Product.slug.ilike(term),
                Product.brand.ilike(term),
                Product.short_description.ilike(term),
                Product.full_description.ilike(term),
                Product.kit_description.ilike(term),
            ),
        )

    # Показываем только товары, размещённые в постаматах выбранного города/постамата,
    # а также товары с активным product_filter (каталожные без привязки к постамату).
    if locker_uuid is not None:
        placed_ids = await aggregate_placed_at_locker(db, locker_uuid)
    elif city_uuid is not None:
        placed_ids = await aggregate_placed_in_city(db, city_uuid)
    else:
        placed_ids = await aggregate_placed_globally(db)

    # Товары с активным product_filter видимы даже без размещения в постамате.
    filter_visible_ids = await _get_filter_only_product_ids(db)

    all_visible_ids = placed_ids | filter_visible_ids
    if all_visible_ids:
        conditions.append(Product.id.in_(all_visible_ids))
    else:
        return {
            "data": {"products": []},
            "meta": {"page": page, "limit": limit, "total": 0},
        }

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
    filters_by_product_id = await load_product_filters_by_product_ids(db, product_ids)
    cover_ids = [p.cover_file_id for p in rows if p.cover_file_id]
    media_map = await load_media_files_by_ids(db, [cid for cid in cover_ids if cid])
    category_ids = list({p.category_id for p in rows})
    category_map: dict[UUID, str] = {}
    if category_ids:
        category_rows = (
            await db.scalars(select(ProductCategory).where(ProductCategory.id.in_(category_ids)))
        ).all()
        category_map = {category.id: category.name for category in category_rows}

    products_payload: list[dict] = []
    for p in rows:
        product_filter = filters_by_product_id.get(p.id)
        if not is_product_visible(p, product_filter):
            continue
        plan = plans.get(p.id)
        cover_url = None
        if p.cover_file_id and p.cover_file_id in media_map:
            cover_url = public_media_url(media_map[p.cover_file_id].file_key)
        u = unit_counts.get(p.id, 0)
        lc = locker_counts.get(p.id, 0)
        is_in_stock = p.id in placed_ids
        products_payload.append(
            resolve_effective_list_item(
            serialize_product_list_item(
                p,
                plan,
                cover_url,
                available=is_in_stock,
                available_locker_count=lc,
                unit_count=u,
                category_name=category_map.get(p.category_id),
            ),
            product_filter,
        )
        )

    return {
        "data": {"products": products_payload},
        "meta": {"page": page, "limit": limit, "total": len(products_payload)},
    }


@router.get("/featured")
async def get_featured_product(
    db: AsyncSession = Depends(get_db),
    cityId: str | None = Query(None),
):
    city_uuid = _parse_uuid_param(cityId, "INVALID_CITY_ID")
    if city_uuid is not None:
        city = await db.get(City, city_uuid)
        if not city:
            raise HTTPException(status_code=404, detail="CITY_NOT_FOUND")

    state = await get_featured_product_state()
    if state is None:
        raise HTTPException(status_code=404, detail="FEATURED_PRODUCT_NOT_FOUND")

    product = await db.get(Product, state.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="FEATURED_PRODUCT_NOT_FOUND")

    product_filter = await load_product_filter(db, product.id)
    if not is_product_visible(product, product_filter):
        raise HTTPException(status_code=410, detail="FEATURED_PRODUCT_INACTIVE")

    payload = await _serialize_product_list_payload(
        db,
        product,
        product_filter,
        city_uuid=city_uuid,
    )
    return {
        "data": {
            "product": payload,
            "activeDate": state.active_date.isoformat(),
        }
    }


@router.get("/{product_id}/busy-dates")
async def get_product_busy_dates(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    lockerId: str | None = Query(None),
    reservationId: str | None = Query(None),
):
    """Список занятых дат (YYYY-MM-DD) для товара.

    Эти даты фронт делает недоступными в календаре выбора периода. Сам
    товар при этом остаётся в каталоге. Если передан ``lockerId`` —
    занятость считается только по этому постамату.
    """
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")

    locker_uuid = _parse_uuid_param(lockerId, "INVALID_LOCKER_ID")
    reservation_uuid = _parse_uuid_param(reservationId, "INVALID_RESERVATION_ID")
    busy = await compute_busy_dates_for_product(
        db, product_id, locker_id=locker_uuid, exclude_reservation_id=reservation_uuid
    )
    return {"data": {"productId": str(product_id), "busyDates": busy}}


@router.get("/{product_id}/pricing")
async def get_product_pricing(
    product_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    lockerId: str = Query(..., description="Pickup point UUID"),
    durationType: str = Query("day"),
    durationValue: int = Query(1, ge=1),
    reservationId: str | None = Query(None),
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    product_filter = await load_product_filter(db, product_id)
    if not is_product_visible(product, product_filter):
        raise HTTPException(status_code=410, detail="PRODUCT_INACTIVE")

    locker_uuid = _parse_uuid_param(lockerId, "INVALID_LOCKER_ID")
    if locker_uuid is None:
        raise HTTPException(status_code=400, detail="INVALID_LOCKER_ID")
    reservation_uuid = _parse_uuid_param(reservationId, "INVALID_RESERVATION_ID")

    locker = await db.get(LockerLocation, locker_uuid)
    if not locker:
        raise HTTPException(status_code=404, detail="LOCKER_NOT_FOUND")
    if locker.status == LockerStatus.OFFLINE:
        raise HTTPException(status_code=409, detail="LOCKER_OFFLINE")
    if locker.status != LockerStatus.ONLINE:
        raise HTTPException(status_code=409, detail="LOCKER_NOT_BOOKABLE")

    filter_plan = find_effective_filter_price_plan(product_filter, durationType, durationValue)
    plan = await find_price_plan(db, product_id, durationType, durationValue)
    if plan is None and filter_plan is None:
        raise HTTPException(status_code=404, detail="PRICE_PLAN_NOT_FOUND")

    try:
        counts = await aggregate_available_inventory_by_product(
            db, locker_uuid, product_id, include_placed=True
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PRICING_FAILED") from exc

    reschedule_reservation = await _load_reschedule_reservation(
        request,
        db,
        reservation_uuid,
        product_id=product_id,
        locker_id=locker_uuid,
    )
    units = counts.get(product_id, 0)
    if units <= 0 and reschedule_reservation is not None:
        units = 1
    if units <= 0:
        raise HTTPException(status_code=409, detail="PRODUCT_NOT_AVAILABLE")

    if filter_plan is not None:
        base = int(filter_plan["baseAmount"])
        currency = str(filter_plan["currency"])
    else:
        assert plan is not None
        base = price_plan_to_minor_units(plan.base_amount, plan.currency)
        currency = plan.currency
    return {
        "data": {
            "productId": str(product_id),
            "lockerId": str(locker_uuid),
            "durationType": durationType,
            "durationValue": durationValue,
            "currency": currency,
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
    request: Request,
    db: AsyncSession = Depends(get_db),
    cityId: str | None = Query(None),
    reservationId: str | None = Query(None),
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    product_filter = await load_product_filter(db, product_id)
    if not is_product_visible(product, product_filter):
        raise HTTPException(status_code=410, detail="PRODUCT_INACTIVE")

    city_uuid = _parse_uuid_param(cityId, "INVALID_CITY_ID")
    reservation_uuid = _parse_uuid_param(reservationId, "INVALID_RESERVATION_ID")
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

    reschedule_reservation = await _load_reschedule_reservation(
        request,
        db,
        reservation_uuid,
        product_id=product_id,
    )
    if reschedule_reservation is not None:
        locker = await db.get(LockerLocation, reschedule_reservation.locker_id)
        if locker is not None and locker.status == LockerStatus.ONLINE:
            existing = next(
                (item for item in lockers if item["lockerId"] == str(locker.id)),
                None,
            )
            if existing is not None:
                existing["availableUnits"] = max(int(existing["availableUnits"]), 1)
            else:
                lockers.append(
                    {
                        "lockerId": str(locker.id),
                        "name": locker.name,
                        "address": locker.address,
                        "status": locker.status.value,
                        "availableUnits": 1,
                    }
                )
                lockers.sort(key=lambda item: item["name"])

    price_plans_out = resolve_effective_price_plans(
        [serialize_base_price_plan(pl) for pl in plans],
        product_filter,
    )

    cover_url = None
    if product.cover_file_id:
        media_map = await load_media_files_by_ids(db, [product.cover_file_id])
        m = media_map.get(product.cover_file_id)
        if m:
            cover_url = public_media_url(m.file_key)

    return {
        "data": {
            "product": resolve_effective_detail_item(
                {
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
                },
                product_filter,
            )
        }
    }
