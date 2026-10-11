"""Очередь на вещь: что можно бронировать и когда бронь становится арендой.

Бронь создаётся по календарю, поэтому вещь может быть занята прямо
сейчас — на руках у клиента, на проверке после возврата, отложена в
ячейке под чужую выдачу — но свободна на выбранные даты. Аренда же — это
PIN на конкретную ячейку: создать её можно, только когда вещь лежит в
постамате и ни за кем не числится. До этого оплаченная бронь ждёт в
PAYMENT_AUTHORIZED, и её дожимает ``auto_confirm_paid_reservations``.

Две незавершённые аренды на одну вещь недопустимы: подтверждение возврата
в админке закрывает все незавершённые аренды юнита разом, и следующая
аренда пропала бы вместе с вернувшейся.
"""
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import (
    InventoryStatus,
    RentalEventSource,
    RentalStatus,
    ReservationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.models.user import User
from backend.utils.lockers_utils import LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY
from backend.utils.products_utils import PLACED_INVENTORY_STATUSES
from backend.utils.reservation_utils import calculate_pickup_expires_at, ensure_utc

ACTIVE_RESERVATION_STATUSES = (
    ReservationStatus.CREATED,
    ReservationStatus.AWAITING_PAYMENT,
    ReservationStatus.PAYMENT_AUTHORIZED,
)

# Аренда оформлена, вещь лежит в ячейке и ждёт своего клиента.
AWAITING_PICKUP_RENTAL_STATUSES = (
    RentalStatus.PICKUP_READY,
    RentalStatus.PICKUP_OPENED,
)

# Вещь на руках у клиента (или возврат ещё не закрыт).
ON_HANDS_RENTAL_STATUSES = (
    RentalStatus.ACTIVE,
    RentalStatus.OVERDUE,
    RentalStatus.RETURN_IN_PROGRESS,
    RentalStatus.INCIDENT,
)

UNFINISHED_RENTAL_STATUSES = AWAITING_PICKUP_RENTAL_STATUSES + ON_HANDS_RENTAL_STATUSES

ON_HANDS_UNIT_STATUSES = (
    InventoryStatus.RENTED,
    InventoryStatus.RETURN_PENDING,
)

# Вещь в ячейке и проверена оператором — её можно выдавать. Всё остальное
# (AWAITING_CONFIRMATION, MAINTENANCE, …) ждёт человека.
HANDOVER_READY_UNIT_STATUSES = (
    InventoryStatus.AVAILABLE,
    InventoryStatus.RESERVED,
)

# Вернувшуюся вещь нельзя бронировать, пока оператор её не проверил, —
# поэтому AWAITING_CONFIRMATION сюда не входит.
BOOKABLE_IN_CELL_STATUSES = tuple(
    status
    for status in PLACED_INVENTORY_STATUSES
    if status != InventoryStatus.AWAITING_CONFIRMATION
)

NEXT_BOOKING_NOTICE_EVENT = "next_booking_notice"


def is_unit_on_hands(unit: InventoryUnit) -> bool:
    return unit.locker_cell_id is None and unit.status in ON_HANDS_UNIT_STATUSES


async def load_bookable_units(
    db: AsyncSession,
    *,
    locker_id: UUID,
    product_id: UUID,
) -> list[InventoryUnit]:
    """Единицы товара, закреплённые за постаматом.

    Это и те, что лежат в его ячейках, и те, что выданы из него и ещё не
    вернулись: ``locker_cell_id`` обнуляется при заборе, поэтому вторые
    находим через незавершённую аренду. Свободны ли они на нужные даты —
    решает вызывающий.
    """
    in_cell_stmt = (
        select(InventoryUnit)
        .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
        .where(
            LockerCell.locker_id == locker_id,
            InventoryUnit.product_id == product_id,
            InventoryUnit.status.in_(BOOKABLE_IN_CELL_STATUSES),
            LockerCell.status.not_in(LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY),
        )
        .order_by(InventoryUnit.created_at.asc())
    )
    units = list((await db.scalars(in_cell_stmt)).all())

    on_hands_stmt = (
        select(InventoryUnit)
        .join(Rental, Rental.inventory_unit_id == InventoryUnit.id)
        .where(
            Rental.pickup_locker_id == locker_id,
            Rental.status.in_(UNFINISHED_RENTAL_STATUSES),
            InventoryUnit.product_id == product_id,
            InventoryUnit.locker_cell_id.is_(None),
            InventoryUnit.status.in_(ON_HANDS_UNIT_STATUSES),
        )
        .order_by(InventoryUnit.created_at.asc())
    )
    seen = {unit.id for unit in units}
    for unit in (await db.scalars(on_hands_stmt)).all():
        if unit.id not in seen:
            seen.add(unit.id)
            units.append(unit)
    return units


def _queue_key(reservation: Reservation) -> tuple[datetime, datetime, str]:
    start = ensure_utc(reservation.pickup_at or reservation.created_at)
    return start, ensure_utc(reservation.created_at), str(reservation.id)


async def _is_unit_held_for_pickup(
    db: AsyncSession,
    unit_id: UUID,
    *,
    now: datetime,
    ignore_reservation_id: UUID | None = None,
) -> bool:
    """Лежит ли вещь в ячейке под чужую, ещё не начатую выдачу."""
    rentals = (
        await db.scalars(
            select(Rental).where(
                Rental.inventory_unit_id == unit_id,
                Rental.status.in_(AWAITING_PICKUP_RENTAL_STATUSES),
            )
        )
    ).all()
    for rental in rentals:
        if ignore_reservation_id is not None and rental.reservation_id == ignore_reservation_id:
            continue
        # Аренда, чей срок целиком в прошлом, — мусор из старых данных, а не
        # живая выдача: шедулер такие уже не трогает, и ждать её незачем.
        if ensure_utc(rental.planned_end_at) > now:
            return True
    return False


async def get_handover_blocker(
    db: AsyncSession,
    reservation: Reservation,
    unit: InventoryUnit | None,
    *,
    now: datetime,
) -> str | None:
    """Почему бронь ещё нельзя превратить в аренду. ``None`` — можно.

    Коды уходят клиенту в ответе confirm, поэтому это часть API.
    """
    if unit is None or unit.locker_cell_id is None:
        return "unit_out"
    cell = await db.get(LockerCell, unit.locker_cell_id)
    if cell is None or cell.locker_id != reservation.locker_id:
        # Вернули в другой постамат города — PIN туда выдавать нельзя,
        # клиент бронировал этот адрес.
        return "unit_elsewhere"
    if unit.status not in HANDOVER_READY_UNIT_STATUSES:
        return "unit_not_ready"
    if await _is_unit_held_for_pickup(
        db, unit.id, now=now, ignore_reservation_id=reservation.id
    ):
        return "unit_held"

    # Очередь: вещь уходит тому, чья выдача раньше. Иначе бронь на более
    # позднюю дату заняла бы ячейку первой, и ранняя её бы не дождалась.
    # Свои же брони не считаем — так выглядит перенос (старая + новая).
    others = (
        await db.scalars(
            select(Reservation).where(
                Reservation.inventory_unit_id == unit.id,
                Reservation.id != reservation.id,
                Reservation.user_id != reservation.user_id,
                Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
        )
    ).all()
    own_key = _queue_key(reservation)
    for other in others:
        if ensure_utc(other.expires_at) <= now:
            continue
        if _queue_key(other) < own_key:
            return "queue"
    return None


async def release_unit_from_reservation(
    db: AsyncSession,
    reservation: Reservation,
    *,
    now: datetime,
) -> None:
    """Снимает с вещи резерв отменённой или истёкшей брони.

    Трогаем только RESERVED: вещь на руках, на проверке или в ремонте
    обязана остаться в своём статусе, даже если бронь на неё отменили.
    И только если на вещь больше никто не претендует.
    """
    unit = await db.get(InventoryUnit, reservation.inventory_unit_id)
    if unit is None or unit.status != InventoryStatus.RESERVED:
        return
    if await _is_unit_held_for_pickup(
        db, unit.id, now=now, ignore_reservation_id=reservation.id
    ):
        return
    others = (
        await db.scalars(
            select(Reservation).where(
                Reservation.inventory_unit_id == unit.id,
                Reservation.id != reservation.id,
                Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
        )
    ).all()
    if any(ensure_utc(other.expires_at) > now for other in others):
        return
    unit.status = InventoryStatus.AVAILABLE


async def waited_for_unit(
    db: AsyncSession,
    reservation: Reservation,
    unit_id: UUID,
) -> bool:
    """Была ли вещь у кого-то другого уже после того, как её забронировали."""
    stmt = (
        select(Rental.id)
        .where(
            Rental.inventory_unit_id == unit_id,
            Rental.actual_end_at.is_not(None),
            Rental.actual_end_at > reservation.created_at,
        )
        .limit(1)
    )
    return (await db.scalars(stmt)).first() is not None


def calculate_handover_pickup_expires_at(
    now: datetime,
    starts_at: datetime,
    *,
    waited: bool,
) -> datetime:
    """Дедлайн забора для аренды, созданной из брони."""
    if starts_at > now:
        return starts_at + timedelta(hours=24)
    standard = calculate_pickup_expires_at(now)
    if waited:
        # Клиент бронировал день заранее, а вещь освободилась уже в этот
        # день. За ним остаётся весь день выдачи, а не три часа с момента,
        # о котором он не знал.
        return max(standard, starts_at + timedelta(hours=24))
    return standard


async def claim_next_booking_notice(
    db: AsyncSession,
    *,
    reservation: Reservation,
    unit: InventoryUnit | None,
) -> str | None:
    """Телефон клиента, у которого вещь на руках, если его пора предупредить.

    Возвращает номер один раз на аренду: отметку ставим событием, чтобы
    повторные confirm (обновление страницы оплаты) не слали SMS снова.
    """
    if unit is None:
        return None
    rental = (
        await db.scalars(
            select(Rental)
            .where(
                Rental.inventory_unit_id == unit.id,
                Rental.status.in_((RentalStatus.ACTIVE, RentalStatus.OVERDUE)),
                Rental.user_id != reservation.user_id,
            )
            .limit(1)
        )
    ).first()
    if rental is None:
        return None
    already_notified = (
        await db.scalars(
            select(RentalEvent.id)
            .where(
                RentalEvent.rental_id == rental.id,
                RentalEvent.event_type == NEXT_BOOKING_NOTICE_EVENT,
            )
            .limit(1)
        )
    ).first()
    if already_notified is not None:
        return None
    renter = await db.get(User, rental.user_id)
    if renter is None or not renter.phone:
        return None
    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type=NEXT_BOOKING_NOTICE_EVENT,
            from_status=rental.status,
            to_status=rental.status,
            source=RentalEventSource.SYSTEM,
            payload_json={"reservationId": str(reservation.id)},
        )
    )
    return renter.phone
