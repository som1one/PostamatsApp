from collections import Counter
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import InventoryStatus, LockerCellStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.price_plan import PricePlan
from backend.models.product import Product

LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY = frozenset(
    {
        LockerCellStatus.FAULT,
        LockerCellStatus.DISABLED,
        LockerCellStatus.OPENED,
    }
)


def is_inventory_available_in_cell(cell: LockerCell, unit: InventoryUnit) -> bool:
    if unit.locker_cell_id != cell.id:
        return False
    if unit.status != InventoryStatus.AVAILABLE:
        return False
    if cell.status in LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY:
        return False
    return True


async def load_locker_availability_counts(
    db: AsyncSession, locker_ids: list[UUID]
) -> dict[UUID, tuple[int, int]]:
    if not locker_ids:
        return {}
    stmt = (
        select(
            LockerCell.locker_id,
            func.count(func.distinct(InventoryUnit.product_id)).label("product_count"),
            func.count(InventoryUnit.id).label("unit_count"),
        )
        .select_from(LockerCell)
        .join(InventoryUnit, InventoryUnit.locker_cell_id == LockerCell.id)
        .where(
            LockerCell.locker_id.in_(locker_ids),
            InventoryUnit.status == InventoryStatus.AVAILABLE,
            LockerCell.status.not_in(LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY),
        )
        .group_by(LockerCell.locker_id)
    )
    result = await db.execute(stmt)
    return {row.locker_id: (row.product_count, row.unit_count) for row in result}


def serialize_locker_location(
    loc: LockerLocation,
    available_product_count: int,
    available_unit_count: int,
) -> dict:
    lat = float(loc.lat) if loc.lat is not None else None
    lon = float(loc.lon) if loc.lon is not None else None
    return {
        "id": str(loc.id),
        "cityId": str(loc.city_id),
        "name": loc.name,
        "address": loc.address,
        "lat": lat,
        "lon": lon,
        "status": loc.status.value,
        "workingHours": loc.working_hours_json,
        "availableProductCount": available_product_count,
        "availableUnitCount": available_unit_count,
    }


async def aggregate_available_inventory_by_product(
    db: AsyncSession,
    locker_id: UUID,
    product_id_filter: UUID | None,
    include_placed: bool = False,
) -> dict[UUID, int]:
    cells = (await db.scalars(select(LockerCell).where(LockerCell.locker_id == locker_id))).all()
    if not cells:
        return {}
    cell_by_id = {c.id: c for c in cells}
    cell_ids = list(cell_by_id.keys())

    stmt = select(InventoryUnit).where(
        InventoryUnit.locker_cell_id.in_(cell_ids),
    )
    if include_placed:
        stmt = stmt.where(InventoryUnit.status.in_((
            InventoryStatus.AVAILABLE,
            InventoryStatus.RESERVED,
            InventoryStatus.RENTED,
            InventoryStatus.RETURN_PENDING,
        )))
    else:
        stmt = stmt.where(InventoryUnit.status == InventoryStatus.AVAILABLE)
    if product_id_filter is not None:
        stmt = stmt.where(InventoryUnit.product_id == product_id_filter)

    units = (await db.scalars(stmt)).all()
    counts: Counter[UUID] = Counter()
    for unit in units:
        cell = cell_by_id.get(unit.locker_cell_id) if unit.locker_cell_id else None
        if cell is None:
            continue
        if not include_placed and not is_inventory_available_in_cell(cell, unit):
            continue
        if include_placed and cell.status in LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY:
            continue
        counts[unit.product_id] += 1
    return dict(counts)


async def fetch_min_price_plans_by_product(
    db: AsyncSession, product_ids: list[UUID]
) -> dict[UUID, PricePlan]:
    if not product_ids:
        return {}
    stmt = (
        select(PricePlan)
        .where(
            PricePlan.product_id.in_(product_ids),
            PricePlan.is_active.is_(True),
        )
        .order_by(PricePlan.product_id, PricePlan.base_amount.asc())
    )
    rows = (await db.scalars(stmt)).all()
    out: dict[UUID, PricePlan] = {}
    for plan in rows:
        if plan.product_id not in out:
            out[plan.product_id] = plan
    return out


async def load_products_by_ids(
    db: AsyncSession, product_ids: list[UUID]
) -> dict[UUID, Product]:
    if not product_ids:
        return {}
    rows = (await db.scalars(select(Product).where(Product.id.in_(product_ids)))).all()
    return {p.id: p for p in rows}


def price_plan_to_minor_units(amount: Decimal, _currency: str) -> int:
    return int(amount * 100)


def build_availability_items(
    product_counts: dict[UUID, int],
    products: dict[UUID, Product],
    plans: dict[UUID, PricePlan],
) -> list[dict]:
    items: list[dict] = []
    for product_id, available_units in sorted(product_counts.items(), key=lambda x: str(x[0])):
        if available_units <= 0:
            continue
        product = products.get(product_id)
        name = product.name if product else ""
        plan = plans.get(product_id)
        if plan:
            items.append(
                {
                    "productId": str(product_id),
                    "productName": name,
                    "availableUnits": available_units,
                    "minDurationType": plan.duration_type,
                    "minDurationValue": plan.duration_value,
                    "priceFrom": price_plan_to_minor_units(plan.base_amount, plan.currency),
                    "currency": plan.currency,
                }
            )
        else:
            items.append(
                {
                    "productId": str(product_id),
                    "productName": name,
                    "availableUnits": available_units,
                    "minDurationType": None,
                    "minDurationValue": None,
                    "priceFrom": None,
                    "currency": "RUB",
                }
            )
    return items


def build_locker_product_summaries(
    product_counts: dict[UUID, int],
    products: dict[UUID, Product],
    plans: dict[UUID, PricePlan],
) -> list[dict]:
    out: list[dict] = []
    for product_id, n in product_counts.items():
        if n <= 0:
            continue
        product = products.get(product_id)
        plan = plans.get(product_id)
        price_from = (
            price_plan_to_minor_units(plan.base_amount, plan.currency) if plan else None
        )
        out.append(
            {
                "productId": str(product_id),
                "name": product.name if product else "",
                "available": True,
                "priceFrom": price_from,
            }
        )
    return out
