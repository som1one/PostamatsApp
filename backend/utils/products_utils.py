from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.enums import InventoryStatus, LockerStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.media_file import MediaFile
from backend.models.price_plan import PricePlan
from backend.models.product_image import ProductImage
from backend.utils.lockers_utils import (
    LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY,
    price_plan_to_minor_units,
)


async def aggregate_available_in_city(
    db: AsyncSession,
    city_id: UUID,
) -> tuple[dict[UUID, int], dict[UUID, int]]:
    stmt = (
        select(
            InventoryUnit.product_id,
            func.count(InventoryUnit.id).label("units"),
            func.count(func.distinct(LockerCell.locker_id)).label("lockers"),
        )
        .select_from(InventoryUnit)
        .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
        .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
        .where(
            LockerLocation.city_id == city_id,
            LockerLocation.status == LockerStatus.ONLINE,
            InventoryUnit.status == InventoryStatus.AVAILABLE,
            LockerCell.status.not_in(LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY),
        )
        .group_by(InventoryUnit.product_id)
    )
    result = await db.execute(stmt)
    units_map: dict[UUID, int] = {}
    lockers_map: dict[UUID, int] = {}
    for row in result:
        units_map[row.product_id] = int(row.units)
        lockers_map[row.product_id] = int(row.lockers)
    return units_map, lockers_map


async def aggregate_available_globally(
    db: AsyncSession,
) -> tuple[dict[UUID, int], dict[UUID, int]]:
    stmt = (
        select(
            InventoryUnit.product_id,
            func.count(InventoryUnit.id).label("units"),
            func.count(func.distinct(LockerCell.locker_id)).label("lockers"),
        )
        .select_from(InventoryUnit)
        .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
        .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
        .where(
            LockerLocation.status == LockerStatus.ONLINE,
            InventoryUnit.status == InventoryStatus.AVAILABLE,
            LockerCell.status.not_in(LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY),
        )
        .group_by(InventoryUnit.product_id)
    )
    result = await db.execute(stmt)
    units_map: dict[UUID, int] = {}
    lockers_map: dict[UUID, int] = {}
    for row in result:
        units_map[row.product_id] = int(row.units)
        lockers_map[row.product_id] = int(row.lockers)
    return units_map, lockers_map


async def load_media_files_by_ids(
    db: AsyncSession,
    file_ids: list[UUID],
) -> dict[UUID, MediaFile]:
    if not file_ids:
        return {}
    rows = (await db.scalars(select(MediaFile).where(MediaFile.id.in_(file_ids)))).all()
    return {m.id: m for m in rows}


def public_media_url(file_key: str) -> str | None:
    if settings.MEDIA_PUBLIC_BASE_URL:
        return f"{settings.MEDIA_PUBLIC_BASE_URL}/{file_key.lstrip('/')}"
    if settings.STORAGE_PROVIDER == "filesystem":
        return f"/assets/runtime-uploads/{file_key.lstrip('/')}"
    return None


async def load_price_plans_for_product(
    db: AsyncSession,
    product_id: UUID,
) -> list[PricePlan]:
    stmt = (
        select(PricePlan)
        .where(
            PricePlan.product_id == product_id,
            PricePlan.is_active.is_(True),
        )
        .order_by(PricePlan.sort_order.asc(), PricePlan.base_amount.asc())
    )
    return list((await db.scalars(stmt)).all())


async def load_product_images_with_urls(
    db: AsyncSession,
    product_id: UUID,
) -> list[dict]:
    stmt = (
        select(ProductImage)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.sort_order.asc(), ProductImage.created_at.asc())
    )
    images = list((await db.scalars(stmt)).all())
    if not images:
        return []
    file_ids = [img.file_id for img in images]
    media_map = await load_media_files_by_ids(db, file_ids)
    out: list[dict] = []
    for img in images:
        media = media_map.get(img.file_id)
        url = public_media_url(media.file_key) if media else None
        out.append(
            {
                "id": str(img.id),
                "fileId": str(img.file_id),
                "url": url,
                "sortOrder": img.sort_order,
            }
        )
    return out


async def load_available_lockers_for_product(
    db: AsyncSession,
    product_id: UUID,
    city_id: UUID | None,
) -> list[dict]:
    stmt = (
        select(
            LockerLocation.id,
            LockerLocation.name,
            LockerLocation.address,
            LockerLocation.status,
            func.count(InventoryUnit.id).label("units"),
        )
        .select_from(InventoryUnit)
        .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
        .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
        .where(
            InventoryUnit.product_id == product_id,
            InventoryUnit.status == InventoryStatus.AVAILABLE,
            LockerCell.status.not_in(LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY),
            LockerLocation.status == LockerStatus.ONLINE,
        )
        .group_by(
            LockerLocation.id,
            LockerLocation.name,
            LockerLocation.address,
            LockerLocation.status,
        )
    )
    if city_id is not None:
        stmt = stmt.where(LockerLocation.city_id == city_id)
    stmt = stmt.order_by(LockerLocation.name.asc())
    result = await db.execute(stmt)
    return [
        {
            "lockerId": str(row.id),
            "name": row.name,
            "address": row.address,
            "status": row.status.value,
            "availableUnits": int(row.units),
        }
        for row in result
    ]


async def find_price_plan(
    db: AsyncSession,
    product_id: UUID,
    duration_type: str,
    duration_value: int,
) -> PricePlan | None:
    stmt = select(PricePlan).where(
        PricePlan.product_id == product_id,
        PricePlan.duration_type == duration_type,
        PricePlan.duration_value == duration_value,
        PricePlan.is_active.is_(True),
    )
    return (await db.scalars(stmt)).first()


def serialize_product_list_item(
    product,
    plan: PricePlan | None,
    cover_url: str | None,
    available: bool,
    available_locker_count: int,
    unit_count: int,
    category_name: str | None = None,
) -> dict:
    price_from = (
        price_plan_to_minor_units(plan.base_amount, plan.currency) if plan else None
    )
    currency = plan.currency if plan else "RUB"
    return {
        "id": str(product.id),
        "categoryId": str(product.category_id),
        "categoryName": category_name,
        "name": product.name,
        "slug": product.slug,
        "coverUrl": cover_url,
        "shortDescription": product.short_description,
        "brand": product.brand,
        "priceFrom": price_from,
        "currency": currency,
        "available": available,
        "availableLockerCount": available_locker_count,
        "availableUnitCount": unit_count,
    }
