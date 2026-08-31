"""Продление активной аренды: расчёт вариантов и применение после оплаты.

Продление — чисто «бумажная» операция: сдвигается ``planned_end_at`` и,
если аренда была просрочена, статус возвращается в ACTIVE. Никаких команд
в постамат здесь нет и быть не должно — товар уже на руках у клиента,
ячейка не участвует.

Деньги берутся через ЮKassa обычным одностадийным платежом типа
``EXTRA_CHARGE`` с привязкой к аренде (``Payment.rental_id``). Сам сдвиг
срока происходит только после подтверждения оплаты — из вебхука, поллинга
``GET /payments/{id}`` или фоновой сверки (см. ``payment_flow``).

Запрошенная длительность хранится в ``RentalEvent`` типа
``extension_requested`` (payload ссылается на платёж) — отдельная таблица
не нужна, а миграции на проде всё равно молча откатываются.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import (
    RentalEventSource,
    RentalStatus,
    ReservationStatus,
)
from backend.models.payment import Payment
from backend.models.price_plan import PricePlan
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.utils.lockers_utils import price_plan_to_minor_units
from backend.utils.product_filters import (
    find_effective_filter_price_plan,
    load_product_filter,
)
from backend.utils.reservation_utils import calculate_planned_end_at, ensure_utc

logger = logging.getLogger(__name__)

EXTENSION_REQUESTED_EVENT = "extension_requested"
EXTENSION_APPLIED_EVENT = "extension_applied"
EXTENSION_NOT_APPLIED_EVENT = "extension_not_applied"

# Продлевать можно только аренду, которая сейчас «на руках».
EXTENDABLE_STATUSES = (RentalStatus.ACTIVE, RentalStatus.OVERDUE)

_BLOCKING_RESERVATION_STATUSES = (
    ReservationStatus.CREATED,
    ReservationStatus.AWAITING_PAYMENT,
    ReservationStatus.PAYMENT_AUTHORIZED,
)


async def get_extension_barrier(db: AsyncSession, rental: Rental) -> datetime | None:
    """Начало ближайшей следующей брони на тот же экземпляр товара.

    Продлить можно только до этого момента (обещание из FAQ). Учитываются
    и живые брони, и уже сконвертированные в PICKUP_READY аренды следующего
    клиента (авто-confirm создаёт их заранее).
    """
    now = datetime.now(timezone.utc)
    candidates: list[datetime] = []

    reservations = (
        await db.scalars(
            select(Reservation).where(
                Reservation.inventory_unit_id == rental.inventory_unit_id,
                Reservation.status.in_(_BLOCKING_RESERVATION_STATUSES),
            )
        )
    ).all()
    for res in reservations:
        # Неоплаченная бронь с истёкшим окном оплаты вот-вот отменится
        # шедулером — не даём ей блокировать продление.
        if (
            res.status != ReservationStatus.PAYMENT_AUTHORIZED
            and ensure_utc(res.expires_at) <= now
        ):
            continue
        candidates.append(ensure_utc(res.pickup_at or res.created_at))

    next_rentals = (
        await db.scalars(
            select(Rental).where(
                Rental.inventory_unit_id == rental.inventory_unit_id,
                Rental.id != rental.id,
                Rental.status == RentalStatus.PICKUP_READY,
            )
        )
    ).all()
    for next_rental in next_rentals:
        candidates.append(ensure_utc(next_rental.starts_at or next_rental.created_at))

    return min(candidates) if candidates else None


async def resolve_extension_price(
    db: AsyncSession,
    product_id,
    duration_type: str,
    duration_value: int,
) -> tuple[PricePlan | None, int, str]:
    """(план, сумма в минорных единицах, валюта) для выбранной длительности.

    Та же логика, что у ``_get_price_plan`` в роутере броней: тариф товара
    плюс возможный override из product_filter. Возвращает (None, 0, "RUB"),
    если тарифа нет — вызывающий сам решает, какой ошибкой ответить.
    """
    from backend.utils.products_utils import find_price_plan

    product_filter = await load_product_filter(db, product_id)
    filter_plan = find_effective_filter_price_plan(
        product_filter, duration_type, duration_value
    )
    plan = await find_price_plan(db, product_id, duration_type, duration_value)
    if plan is None:
        return None, 0, "RUB"
    if filter_plan is not None:
        return plan, int(filter_plan["baseAmount"]), str(filter_plan["currency"])
    return plan, price_plan_to_minor_units(plan.base_amount, plan.currency), plan.currency


async def list_extension_options(db: AsyncSession, rental: Rental, product_id) -> dict:
    """Варианты продления по активным тарифам товара + потолок по времени."""
    barrier = await get_extension_barrier(db, rental)
    base_end = ensure_utc(rental.planned_end_at)

    product_filter = await load_product_filter(db, product_id)
    plans = (
        await db.scalars(
            select(PricePlan)
            .where(
                PricePlan.product_id == product_id,
                PricePlan.is_active.is_(True),
            )
            .order_by(PricePlan.sort_order.asc(), PricePlan.duration_value.asc())
        )
    ).all()

    options: list[dict] = []
    for plan in plans:
        filter_plan = find_effective_filter_price_plan(
            product_filter, plan.duration_type, plan.duration_value
        )
        if filter_plan is not None:
            amount_minor = int(filter_plan["baseAmount"])
            currency = str(filter_plan["currency"])
        else:
            amount_minor = price_plan_to_minor_units(plan.base_amount, plan.currency)
            currency = plan.currency
        new_end = calculate_planned_end_at(
            base_end, plan.duration_type, plan.duration_value
        )
        options.append(
            {
                "durationType": plan.duration_type,
                "durationValue": plan.duration_value,
                "name": plan.name,
                "amount": amount_minor,
                "currency": currency,
                "newEndAt": new_end.isoformat(),
                "available": barrier is None or new_end <= barrier,
            }
        )

    return {
        "rentalId": str(rental.id),
        "status": rental.status.value,
        "currentEndAt": base_end.isoformat(),
        "maxEndAt": barrier.isoformat() if barrier is not None else None,
        "options": options,
    }


async def apply_rental_extension_for_payment(
    db: AsyncSession,
    payment: Payment,
    *,
    source: RentalEventSource = RentalEventSource.SYSTEM,
    now: datetime | None = None,
) -> bool:
    """Сдвигает срок аренды по оплаченному платежу продления. Идемпотентно.

    Не коммитит — транзакцией управляет вызывающий код. True — срок
    изменился (или зафиксирован отказ). Ячейки постамата не трогаются.
    """
    if payment.rental_id is None:
        return False

    rental = await db.get(Rental, payment.rental_id)
    if rental is None:
        return False

    events = (
        await db.scalars(
            select(RentalEvent).where(
                RentalEvent.rental_id == rental.id,
                RentalEvent.event_type.in_(
                    (
                        EXTENSION_REQUESTED_EVENT,
                        EXTENSION_APPLIED_EVENT,
                        EXTENSION_NOT_APPLIED_EVENT,
                    )
                ),
            )
        )
    ).all()
    pid = str(payment.id)
    requested = next(
        (
            ev
            for ev in events
            if ev.event_type == EXTENSION_REQUESTED_EVENT
            and (ev.payload_json or {}).get("paymentId") == pid
        ),
        None,
    )
    if requested is None:
        return False
    already_settled = any(
        ev.event_type in (EXTENSION_APPLIED_EVENT, EXTENSION_NOT_APPLIED_EVENT)
        and (ev.payload_json or {}).get("paymentId") == pid
        for ev in events
    )
    if already_settled:
        return False

    payload = requested.payload_json or {}
    duration_type = str(payload.get("durationType") or "day")
    duration_value = int(payload.get("durationValue") or 1)
    resolved_now = now or datetime.now(timezone.utc)
    prev_status = rental.status

    # Аренда успела завершиться/отмениться, пока клиент оплачивал —
    # срок двигать некуда. Фиксируем событие (для поддержки и возврата
    # денег вручную) и больше к этому платежу не возвращаемся.
    if rental.status not in (
        RentalStatus.ACTIVE,
        RentalStatus.OVERDUE,
        RentalStatus.RETURN_IN_PROGRESS,
    ):
        logger.warning(
            "Extension payment %s for rental %s arrived in status %s — not applied",
            payment.id,
            rental.id,
            rental.status.value,
        )
        db.add(
            RentalEvent(
                rental_id=rental.id,
                event_type=EXTENSION_NOT_APPLIED_EVENT,
                from_status=prev_status,
                to_status=prev_status,
                source=source,
                payload_json={
                    "paymentId": pid,
                    "reason": f"rental_status_{rental.status.value}",
                },
            )
        )
        return True

    prev_end = ensure_utc(rental.planned_end_at)
    new_end = calculate_planned_end_at(prev_end, duration_type, duration_value)
    rental.planned_end_at = new_end
    if rental.status == RentalStatus.OVERDUE and new_end > resolved_now:
        rental.status = RentalStatus.ACTIVE
        rental.overdue_started_at = None

    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type=EXTENSION_APPLIED_EVENT,
            from_status=prev_status,
            to_status=rental.status,
            source=source,
            payload_json={
                "paymentId": pid,
                "durationType": duration_type,
                "durationValue": duration_value,
                "previousEndAt": prev_end.isoformat(),
                "newEndAt": new_end.isoformat(),
            },
        )
    )
    logger.info(
        "Rental %s extended by %s %s until %s (payment %s)",
        rental.id,
        duration_value,
        duration_type,
        new_end.isoformat(),
        payment.id,
    )
    return True
