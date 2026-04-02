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
from backend.utils.reservation_utils import ensure_utc
from backend.utils.yookassa_service import create_yookassa_preauth_payment

logger = logging.getLogger(__name__)


def payment_blocks_new_preauth(p: Payment) -> bool:
    return p.status not in (PaymentStatus.FAILED, PaymentStatus.CANCELLED, PaymentStatus.REFUNDED)


async def ensure_no_active_payment_for_reservation(db: AsyncSession, reservation_id: UUID) -> None:
    stmt = select(Payment).where(Payment.reservation_id == reservation_id)
    rows = (await db.scalars(stmt)).all()
    for p in rows:
        if payment_blocks_new_preauth(p):
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail="PAYMENT_ALREADY_EXISTS")


async def create_preauth_for_reservation(
    db: AsyncSession,
    *,
    user: User,
    reservation: Reservation,
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

    return_url = settings.YOOKASSA_RETURN_URL or "https://example.com/payment-return"
    metadata = {
        "internal_payment_id": str(payment.id),
        "reservation_id": str(reservation.id),
        "user_id": str(user.id),
    }

    try:
        yk = await create_yookassa_preauth_payment(
            amount_value=amount,
            currency=currency,
            return_url=return_url,
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


async def process_yookassa_webhook(
    db: AsyncSession,
    *,
    event: str | None,
    object_id: str | None,
    object_status: str | None,
    raw_payload: dict[str, Any],
) -> bool:
    """Возвращает True если событие принято (в т.ч. дубликат)."""
    from fastapi import HTTPException

    if not object_id:
        raise HTTPException(status_code=400, detail="INVALID_WEBHOOK_PAYLOAD")

    payment = (
        await db.scalars(select(Payment).where(Payment.provider_payment_id == object_id).limit(1))
    ).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")

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

    new_status = _map_yookassa_status_to_payment_status(object_status)
    if new_status is not None and payment.type == PaymentType.PREAUTH:
        if new_status == PaymentStatus.AUTHORIZED:
            payment.status = PaymentStatus.AUTHORIZED
            payment.processed_at = now
        elif new_status == PaymentStatus.CAPTURED:
            payment.status = PaymentStatus.CAPTURED
            payment.processed_at = now
        elif new_status == PaymentStatus.FAILED:
            payment.status = PaymentStatus.FAILED
            payment.processed_at = now
            payment.failure_code = object_status
        elif new_status == PaymentStatus.PENDING:
            payment.status = PaymentStatus.PENDING

    if payment.status == PaymentStatus.AUTHORIZED and payment.reservation_id:
        res = await db.get(Reservation, payment.reservation_id)
        if res is not None and res.status == ReservationStatus.AWAITING_PAYMENT:
            res.status = ReservationStatus.PAYMENT_AUTHORIZED

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return True
    return True
