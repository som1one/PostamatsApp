from uuid import UUID

from sqlalchemy import and_, case, func, select
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
from backend.utils.reservation_utils import calculate_planned_end_at


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
            # Витрина показывает товары и для постаматов на обслуживании
            # (`MAINTENANCE`/`DEGRADED`) — пользователь видит карточки,
            # но при попытке оформить аренду reservation вернёт
            # ``LOCKER_NOT_BOOKABLE``. Полностью скрываем только OFFLINE.
            LockerLocation.status != LockerStatus.OFFLINE,
            InventoryUnit.status.in_((InventoryStatus.AVAILABLE, InventoryStatus.AWAITING_CONFIRMATION)),
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
            # См. комментарий в aggregate_available_in_city — допускаем
            # MAINTENANCE/DEGRADED, чтобы товары не пропадали с витрины,
            # пока постамат на обслуживании.
            LockerLocation.status != LockerStatus.OFFLINE,
            InventoryUnit.status.in_((InventoryStatus.AVAILABLE, InventoryStatus.AWAITING_CONFIRMATION)),
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


# Статусы инвентаря, означающие, что единица физически размещена в
# постамате и относится к каталогу, даже если прямо сейчас занята бронью
# или арендой. Используются для видимости товара в каталоге: товар не
# должен исчезать, пока его экземпляр стоит в ячейке — занятость
# отражается в календаре отдельными датами.
PLACED_INVENTORY_STATUSES = (
    InventoryStatus.AVAILABLE,
    InventoryStatus.RESERVED,
    InventoryStatus.RENTED,
    InventoryStatus.RETURN_PENDING,
    InventoryStatus.AWAITING_CONFIRMATION,
)


async def aggregate_placed_in_city(
    db: AsyncSession,
    city_id: UUID,
) -> set[UUID]:
    """Множество product_id, у которых есть размещённый инвентарь в городе.

    В отличие от ``aggregate_available_in_city`` учитывает не только
    свободные единицы, но и занятые бронью/арендой — чтобы товар не
    пропадал из каталога, пока экземпляр физически в постамате.

    Также учитывает юниты, которые сейчас на руках у арендатора
    (locker_cell_id IS NULL, статус RENTED) — находим их через таблицу
    Rental по pickup_locker_id.
    """
    from backend.models.rental import Rental
    from backend.models.enums import RentalStatus

    # 1) Юниты, физически стоящие в ячейках постаматов города
    stmt_in_cell = (
        select(InventoryUnit.product_id)
        .select_from(InventoryUnit)
        .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
        .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
        .where(
            LockerLocation.city_id == city_id,
            LockerLocation.status != LockerStatus.OFFLINE,
            InventoryUnit.status.in_(PLACED_INVENTORY_STATUSES),
        )
        .distinct()
    )
    result_in_cell = {row for row in (await db.scalars(stmt_in_cell)).all()}

    # 2) Юниты на руках у арендатора (locker_cell_id = NULL, статус RENTED)
    active_rental_statuses = (
        RentalStatus.PICKUP_READY,
        RentalStatus.PICKUP_OPENED,
        RentalStatus.ACTIVE,
        RentalStatus.OVERDUE,
        RentalStatus.RETURN_IN_PROGRESS,
        RentalStatus.INCIDENT,
    )
    stmt_rented_out = (
        select(InventoryUnit.product_id)
        .select_from(InventoryUnit)
        .join(Rental, Rental.inventory_unit_id == InventoryUnit.id)
        .join(LockerLocation, Rental.pickup_locker_id == LockerLocation.id)
        .where(
            LockerLocation.city_id == city_id,
            InventoryUnit.locker_cell_id.is_(None),
            InventoryUnit.status.in_((InventoryStatus.RENTED, InventoryStatus.RETURN_PENDING)),
            Rental.status.in_(active_rental_statuses),
        )
        .distinct()
    )
    result_rented_out = {row for row in (await db.scalars(stmt_rented_out)).all()}

    return result_in_cell | result_rented_out


async def aggregate_placed_globally(db: AsyncSession) -> set[UUID]:
    from backend.models.rental import Rental
    from backend.models.enums import RentalStatus

    stmt_in_cell = (
        select(InventoryUnit.product_id)
        .select_from(InventoryUnit)
        .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
        .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
        .where(
            LockerLocation.status != LockerStatus.OFFLINE,
            InventoryUnit.status.in_(PLACED_INVENTORY_STATUSES),
        )
        .distinct()
    )
    result_in_cell = {row for row in (await db.scalars(stmt_in_cell)).all()}

    active_rental_statuses = (
        RentalStatus.PICKUP_READY,
        RentalStatus.PICKUP_OPENED,
        RentalStatus.ACTIVE,
        RentalStatus.OVERDUE,
        RentalStatus.RETURN_IN_PROGRESS,
        RentalStatus.INCIDENT,
    )
    stmt_rented_out = (
        select(InventoryUnit.product_id)
        .select_from(InventoryUnit)
        .join(Rental, Rental.inventory_unit_id == InventoryUnit.id)
        .where(
            InventoryUnit.locker_cell_id.is_(None),
            InventoryUnit.status.in_((InventoryStatus.RENTED, InventoryStatus.RETURN_PENDING)),
            Rental.status.in_(active_rental_statuses),
        )
        .distinct()
    )
    result_rented_out = {row for row in (await db.scalars(stmt_rented_out)).all()}

    return result_in_cell | result_rented_out


async def aggregate_placed_at_locker(
    db: AsyncSession,
    locker_id: UUID,
) -> set[UUID]:
    from backend.models.rental import Rental
    from backend.models.enums import RentalStatus

    stmt_in_cell = (
        select(InventoryUnit.product_id)
        .select_from(InventoryUnit)
        .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
        .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
        .where(
            LockerCell.locker_id == locker_id,
            LockerLocation.status != LockerStatus.OFFLINE,
            InventoryUnit.status.in_(PLACED_INVENTORY_STATUSES),
        )
        .distinct()
    )
    result_in_cell = {row for row in (await db.scalars(stmt_in_cell)).all()}

    active_rental_statuses = (
        RentalStatus.PICKUP_READY,
        RentalStatus.PICKUP_OPENED,
        RentalStatus.ACTIVE,
        RentalStatus.OVERDUE,
        RentalStatus.RETURN_IN_PROGRESS,
        RentalStatus.INCIDENT,
    )
    stmt_rented_out = (
        select(InventoryUnit.product_id)
        .select_from(InventoryUnit)
        .join(Rental, Rental.inventory_unit_id == InventoryUnit.id)
        .where(
            Rental.pickup_locker_id == locker_id,
            InventoryUnit.locker_cell_id.is_(None),
            InventoryUnit.status.in_((InventoryStatus.RENTED, InventoryStatus.RETURN_PENDING)),
            Rental.status.in_(active_rental_statuses),
        )
        .distinct()
    )
    result_rented_out = {row for row in (await db.scalars(stmt_rented_out)).all()}

    return result_in_cell | result_rented_out


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
            func.sum(
                case(
                    (
                        and_(
                            InventoryUnit.status.in_((InventoryStatus.AVAILABLE, InventoryStatus.AWAITING_CONFIRMATION)),
                            LockerCell.status.not_in(LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY)
                        ),
                        1
                    ),
                    else_=0,
                )
            ).label("units"),
        )
        .select_from(InventoryUnit)
        .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
        .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
        .where(
            InventoryUnit.product_id == product_id,
            InventoryUnit.status.in_(PLACED_INVENTORY_STATUSES),
            # Скрываем только OFFLINE; MAINTENANCE/DEGRADED показываем
            # с пометкой статуса — фронт делает кнопку «оформить» серой.
            LockerLocation.status != LockerStatus.OFFLINE,
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
            "availableUnits": int(row.units or 0),
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


async def compute_busy_dates_for_product(
    db: AsyncSession,
    product_id: UUID,
    *,
    locker_id: UUID | None = None,
    exclude_reservation_id: UUID | None = None,
) -> list[str]:
    """Возвращает отсортированный список занятых дат (YYYY-MM-DD, локальный
    московский день) для товара.

    Дата считается занятой, если на неё приходится активная бронь или
    аренда экземпляра этого товара. Если передан ``locker_id`` — считаем
    занятость только по этому постамату (товар в разных постаматах
    независим). Эти даты фронт делает недоступными в календаре, при этом
    сам товар остаётся в каталоге.

    Важно: метод не отвечает за защиту от двойного бронирования (она
    обеспечивается статусом инвентаря на этапе создания брони). Это лишь
    подсказка для UI, какие дни заняты.
    """

    from datetime import date, datetime, time, timedelta, timezone

    from backend.models.inventory_unit import InventoryUnit
    from backend.models.locker_cell import LockerCell
    from backend.models.rental import Rental
    from backend.models.reservation import Reservation
    from backend.models.enums import RentalStatus, ReservationStatus

    local_tz = timezone(timedelta(hours=3))

    def _to_local_date(value: datetime) -> date:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(local_tz).date()

    busy: set[date] = set()

    # 1) Брони, занимающие даты: ещё не отменённые/не истёкшие.
    active_res_statuses = (
        ReservationStatus.CREATED,
        ReservationStatus.AWAITING_PAYMENT,
        ReservationStatus.PAYMENT_AUTHORIZED,
    )
    res_conditions = [
        Reservation.product_id == product_id,
        Reservation.status.in_(active_res_statuses),
    ]
    if locker_id is not None:
        res_conditions.append(Reservation.locker_id == locker_id)
    if exclude_reservation_id is not None:
        res_conditions.append(Reservation.id != exclude_reservation_id)
    reservations = list((await db.scalars(select(Reservation).where(*res_conditions))).all())

    # 2) Аренды, занимающие даты: ещё не завершённые/не отменённые.
    # Аренду связываем с товаром через её inventory_unit (reservation_id
    # может быть NULL для ручных/служебных кейсов).
    from sqlalchemy import or_, and_
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)

    busy_rental_statuses = (
        RentalStatus.PICKUP_READY,
        RentalStatus.PICKUP_OPENED,
        RentalStatus.ACTIVE,
        RentalStatus.OVERDUE,
        RentalStatus.RETURN_IN_PROGRESS,
        RentalStatus.INCIDENT,
    )
    rental_conditions = [
        or_(
            Rental.status.in_(busy_rental_statuses),
            and_(
                Rental.status == RentalStatus.COMPLETED,
                Rental.actual_end_at >= two_days_ago,
            )
        ),
        InventoryUnit.product_id == product_id,
    ]
    if locker_id is not None:
        rental_conditions.append(Rental.pickup_locker_id == locker_id)
    if exclude_reservation_id is not None:
        # Exclude the rental generated by the reservation we're rescheduling
        rental_conditions.append(
            or_(
                Rental.reservation_id.is_(None),
                Rental.reservation_id != exclude_reservation_id,
            )
        )
    rentals = list(
        (
            await db.scalars(
                select(Rental)
                .join(InventoryUnit, Rental.inventory_unit_id == InventoryUnit.id)
                .where(*rental_conditions)
            )
        ).all()
    )

    def _mark_range(start: datetime | None, end: datetime | None) -> None:
        if start is None or end is None:
            return
        start_d = _to_local_date(start)
        end_d = _to_local_date(end)
        if end_d < start_d:
            return
        cur = start_d
        # Защита от аномально больших диапазонов (например, кривой
        # planned_end_at) — не строим больше года дат.
        for _ in range(366):
            busy.add(cur)
            if cur >= end_d:
                break
            cur = cur + timedelta(days=1)

    for res in reservations:
        start = res.pickup_at or res.created_at
        end = calculate_planned_end_at(
            start, res.duration_type, res.duration_value
        )
        _mark_range(start, end)

    for rental in rentals:
        start = rental.starts_at or rental.created_at
        if rental.status == RentalStatus.COMPLETED:
            if not rental.actual_end_at:
                continue
            end = rental.actual_end_at + timedelta(hours=24)
        else:
            end = rental.planned_end_at
        _mark_range(start, end)

    return sorted(d.isoformat() for d in busy)
