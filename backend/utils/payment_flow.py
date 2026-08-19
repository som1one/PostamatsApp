import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.enums import PaymentStatus, PaymentType, ReservationStatus
from backend.models.payment import Payment
from backend.models.payment_event import PaymentEvent
from backend.models.reservation import Reservation
from backend.models.user import User
from backend.utils.lockers_utils import price_plan_to_minor_units
from backend.utils.reservation_utils import (
    calculate_paid_reservation_expires_at,
    ensure_utc,
)
from backend.utils.yookassa_service import create_yookassa_preauth_payment

logger = logging.getLogger(__name__)


def payment_blocks_new_preauth(p: Payment) -> bool:
    return p.status in (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED)


async def ensure_no_active_payment_for_reservation(db: AsyncSession, reservation_id: UUID) -> None:
    from fastapi import HTTPException

    stmt = select(Payment).where(Payment.reservation_id == reservation_id)
    rows = (await db.scalars(stmt)).all()

    # Платёж мог давно пройти, а у нас остаться PENDING (уведомление ЮKassa
    # не дошло). Если не спросить провайдера, клиент, которому карточка всё
    # ещё показывает «Оплатить», заплатит второй раз.
    reconciled = False
    for p in rows:
        if p.status in (PaymentStatus.CREATED, PaymentStatus.PENDING) and p.provider_payment_id:
            reconciled = await sync_payment_with_provider(db, p) or reconciled
    if reconciled:
        await db.commit()

    for p in rows:
        if payment_blocks_new_preauth(p):
            raise HTTPException(status_code=409, detail="PAYMENT_ALREADY_EXISTS")


async def create_preauth_for_reservation(
    db: AsyncSession,
    *,
    user: User,
    reservation: Reservation,
    return_url: str | None = None,
) -> dict:
    from fastapi import HTTPException

    now = datetime.now(timezone.utc)
    if reservation.status != ReservationStatus.AWAITING_PAYMENT:
        raise HTTPException(status_code=409, detail="RESERVATION_NOT_PAYABLE")
    if ensure_utc(reservation.expires_at) <= now:
        raise HTTPException(status_code=409, detail="RESERVATION_EXPIRED")

    await ensure_no_active_payment_for_reservation(db, reservation.id)

    amount = reservation.preauth_amount or reservation.quoted_amount
    currency = "RUB"

    payment = Payment(
        user_id=user.id,
        reservation_id=reservation.id,
        rental_id=None,
        provider="yookassa",
        provider_payment_id=None,
        type=PaymentType.PREAUTH,
        status=PaymentStatus.PENDING,
        amount=amount,
        currency=currency,
    )
    db.add(payment)
    await db.flush()

    resolved_return_url = (
        return_url
        or settings.YOOKASSA_RETURN_URL
        or (
            f"{settings.WEB_APP_ORIGIN}/payment/return"
            if settings.WEB_APP_ORIGIN
            else None
        )
        or "https://example.com/payment-return"
    )
    metadata = {
        "internal_payment_id": str(payment.id),
        "reservation_id": str(reservation.id),
        "user_id": str(user.id),
    }

    try:
        yk = await create_yookassa_preauth_payment(
            amount_value=amount,
            currency=currency,
            return_url=resolved_return_url,
            metadata=metadata,
        )
    except Exception as exc:
        await db.rollback()
        from fastapi import HTTPException

        logger.exception("YooKassa preauth failed")
        raise HTTPException(status_code=502, detail="YOOKASSA_REQUEST_FAILED") from exc

    payment.provider_payment_id = yk["provider_payment_id"]
    await db.commit()
    await db.refresh(payment)

    amount_minor = price_plan_to_minor_units(payment.amount, payment.currency)
    return {
        "payment": {
            "id": str(payment.id),
            "type": payment.type.value,
            "status": payment.status.value,
            "amount": amount_minor,
            "currency": payment.currency,
        },
        "confirmation": {
            "type": yk.get("confirmation_type", "redirect"),
            "confirmationUrl": yk.get("confirmation_url"),
        },
    }


def serialize_payment_for_user(p: Payment) -> dict:
    amount_minor = price_plan_to_minor_units(p.amount, p.currency)
    processed = None
    if p.processed_at:
        processed = p.processed_at.isoformat() if hasattr(p.processed_at, "isoformat") else str(p.processed_at)
    return {
        "id": str(p.id),
        "type": p.type.value,
        "status": p.status.value,
        "amount": amount_minor,
        "currency": p.currency,
        "failureCode": p.failure_code,
        "failureMessage": p.failure_message,
        "processedAt": processed,
    }


def _map_yookassa_status_to_payment_status(yk_status: str | None) -> PaymentStatus | None:
    if not yk_status:
        return None
    s = yk_status.lower()
    if s == "waiting_for_capture":
        return PaymentStatus.AUTHORIZED
    if s == "succeeded":
        return PaymentStatus.CAPTURED
    if s in ("canceled", "cancelled"):
        return PaymentStatus.FAILED
    if s == "pending":
        return PaymentStatus.PENDING
    return None


PAID_PAYMENT_STATUSES = (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED)

# Из этих статусов платёж уже не выходит: деньги списаны и возвращены, либо
# холд снят. Поздно пришедшее уведомление «succeeded» не должно их перебить.
_SETTLED_PAYMENT_STATUSES = (
    PaymentStatus.CAPTURED,
    PaymentStatus.CANCELLED,
    PaymentStatus.REFUNDED,
)


async def apply_payment_status_transition(
    db: AsyncSession,
    payment: Payment,
    new_status: PaymentStatus | None,
    *,
    now: datetime | None = None,
    failure_code: str | None = None,
) -> bool:
    """Переводит платёж в новый статус и подтягивает за ним бронь.

    Единая точка перехода для всех источников статуса: вебхука, ручного
    поллинга из GET /payments/{id} и фоновой сверки. Не коммитит —
    транзакцией управляет вызывающий код.

    Возвращает True, если что-то изменилось.
    """
    if new_status is None or payment.type != PaymentType.PREAUTH:
        return False
    if payment.status == new_status:
        # Статус тот же, но бронь могла отстать (например, вебхук успел
        # обновить платёж до того, как появилась связь с бронью).
        return await _sync_reservation_with_payment(db, payment, now=now)
    if payment.status in _SETTLED_PAYMENT_STATUSES:
        return False
    if new_status == PaymentStatus.PENDING:
        # Назад в pending платёж не откатываем.
        return False

    resolved_now = now or datetime.now(timezone.utc)
    payment.status = new_status
    payment.processed_at = resolved_now
    if new_status == PaymentStatus.FAILED and failure_code:
        payment.failure_code = failure_code

    await _sync_reservation_with_payment(db, payment, now=resolved_now)
    return True


async def _sync_reservation_with_payment(
    db: AsyncSession,
    payment: Payment,
    *,
    now: datetime | None = None,
) -> bool:
    """Оплаченный платёж → бронь PAYMENT_AUTHORIZED с продлённым сроком."""
    if payment.status not in PAID_PAYMENT_STATUSES or not payment.reservation_id:
        return False
    res = await db.get(Reservation, payment.reservation_id)
    if res is None or res.status not in (
        ReservationStatus.CREATED,
        ReservationStatus.AWAITING_PAYMENT,
    ):
        return False
    # Одностадийная оплата: succeeded → CAPTURED сразу подтверждает бронь.
    # Двухстадийная (waiting_for_capture → AUTHORIZED) тоже поддержана.
    res.status = ReservationStatus.PAYMENT_AUTHORIZED
    # Оплаченная бронь живёт до конца дня выдачи, а не 2 часа окна оплаты —
    # иначе шедулер отменит её вместе с деньгами клиента.
    res.expires_at = calculate_paid_reservation_expires_at(res)
    return True


async def sync_payment_with_provider(
    db: AsyncSession,
    payment: Payment,
    *,
    now: datetime | None = None,
) -> bool:
    """Спрашивает актуальный статус у ЮKassa и применяет его. Не коммитит.

    Нужна везде, где нельзя полагаться на уведомление: клиент мог оплатить
    через СБП и не вернуться на /payment/return, а уведомление могло не
    дойти (или прийти позже). Возвращает True, если что-то изменилось.
    """
    from backend.utils.yookassa_service import fetch_yookassa_payment_status

    if not payment.provider_payment_id or payment.status not in (
        PaymentStatus.CREATED,
        PaymentStatus.PENDING,
        PaymentStatus.AUTHORIZED,
    ):
        return False
    yk_status = await fetch_yookassa_payment_status(payment.provider_payment_id)
    if yk_status is None:
        return False
    return await apply_payment_status_transition(
        db,
        payment,
        _map_yookassa_status_to_payment_status(yk_status),
        now=now,
        failure_code=yk_status,
    )


async def process_yookassa_webhook(
    db: AsyncSession,
    *,
    event: str | None,
    object_id: str | None,
    object_status: str | None,
    raw_payload: dict[str, Any],
    trusted_source: bool = False,
) -> bool:
    """Обрабатывает уведомление ЮKassa. True — событие принято.

    Тело уведомления само по себе не доверенное (подписи у ЮKassa нет),
    поэтому статус подтверждаем запросом к API. Телу верим только если
    уведомление пришло с официального IP, а API недоступен.
    """
    from fastapi import HTTPException

    if not object_id:
        raise HTTPException(status_code=400, detail="INVALID_WEBHOOK_PAYLOAD")

    payment = (
        await db.scalars(select(Payment).where(Payment.provider_payment_id == object_id).limit(1))
    ).first()
    if payment is None:
        # Платёж не наш (или чужой магазин на том же URL). Отвечаем 200,
        # иначе ЮKassa будет ретраить это уведомление ещё сутки.
        logger.warning("YooKassa notification for unknown payment %s", object_id)
        return False

    provider_event_id = f"{event or 'event'}:{object_id}"
    existing = (
        await db.scalars(
            select(PaymentEvent).where(PaymentEvent.provider_event_id == provider_event_id).limit(1)
        )
    ).first()
    if existing is not None:
        return True

    now = datetime.now(timezone.utc)
    ev = PaymentEvent(
        payment_id=payment.id,
        provider_event_id=provider_event_id,
        event_type=event or "unknown",
        payload_json=raw_payload,
        received_at=now,
    )
    db.add(ev)

    changed = await sync_payment_with_provider(db, payment, now=now)
    if not changed and trusted_source:
        # API не ответил, но отправитель — официальный IP ЮKassa: применяем
        # статус из тела, иначе оплата зависнет до следующей сверки.
        await apply_payment_status_transition(
            db,
            payment,
            _map_yookassa_status_to_payment_status(object_status),
            now=now,
            failure_code=object_status,
        )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return True
    return True
