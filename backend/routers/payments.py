from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.enums import PaymentStatus, PaymentType, ReservationStatus
from backend.models.reservation import Reservation
from backend.core.database import get_db
from backend.schemas.payment_schemas import PreauthPayload, YooKassaWebhookBody
from backend.utils.auth_utils import get_current_client_user
from backend.utils.payment_flow import (
    create_preauth_for_reservation,
    process_yookassa_webhook,
    serialize_payment_for_user,
)
from backend.models.payment import Payment

router = APIRouter(prefix="/payments", tags=["payments"])
yookassa_webhook_router = APIRouter(prefix="/payments/webhooks", tags=["payments"])


@router.post("/preauth")
async def payments_preauth(
    request: Request,
    payload: PreauthPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_client_user(request, db)
    reservation = await db.get(Reservation, payload.reservationId)
    if reservation is None or reservation.user_id != user.id:
        raise HTTPException(status_code=404, detail="RESERVATION_NOT_FOUND")

    out = await create_preauth_for_reservation(
        db,
        user=user,
        reservation=reservation,
        return_url=payload.returnUrl,
    )
    return {"data": out}


@router.get("/{payment_id}")
async def get_payment(
    payment_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_client_user(request, db)
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")
    if payment.user_id != user.id:
        raise HTTPException(status_code=403, detail="PAYMENT_FORBIDDEN")

    # Active polling fallback: если платёж pending дольше 10с и есть
    # provider_payment_id — проверяем статус напрямую в ЮKassa.
    # Это покрывает случай, когда webhook не дошёл или задержался.
    if (
        payment.status == PaymentStatus.PENDING
        and payment.provider_payment_id
        and payment.created_at is not None
    ):
        from backend.utils.yookassa_service import fetch_yookassa_payment_status
        from backend.utils.payment_flow import _map_yookassa_status_to_payment_status

        age_seconds = (datetime.now(timezone.utc) - payment.created_at).total_seconds()
        if age_seconds > 10:
            yk_status = await fetch_yookassa_payment_status(payment.provider_payment_id)
            if yk_status:
                new_status = _map_yookassa_status_to_payment_status(yk_status)
                if new_status is not None and new_status != PaymentStatus.PENDING:
                    payment.status = new_status
                    payment.processed_at = datetime.now(timezone.utc)
                    # Также обновляем бронь если платёж confirmed
                    if new_status in (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED) and payment.reservation_id:
                        res = await db.get(Reservation, payment.reservation_id)
                        if res is not None and res.status == ReservationStatus.AWAITING_PAYMENT:
                            res.status = ReservationStatus.PAYMENT_AUTHORIZED
                    await db.commit()
                    await db.refresh(payment)

    return {"data": {"payment": serialize_payment_for_user(payment)}}


@router.post("/{payment_id}/authorize-dev-stub")
async def authorize_payment_dev_stub(
    payment_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_client_user(request, db)
    if not settings.YOOKASSA_DEV_STUB:
        raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")

    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")
    if payment.user_id != user.id:
        raise HTTPException(status_code=403, detail="PAYMENT_FORBIDDEN")
    if payment.type != PaymentType.PREAUTH:
        raise HTTPException(status_code=409, detail="PAYMENT_NOT_AUTHORIZABLE")

    if payment.status in (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED):
        return {"data": {"payment": serialize_payment_for_user(payment)}}
    if payment.status != PaymentStatus.PENDING:
        raise HTTPException(status_code=409, detail="PAYMENT_NOT_AUTHORIZABLE")

    now = datetime.now(timezone.utc)
    payment.status = PaymentStatus.AUTHORIZED
    payment.processed_at = now

    if payment.reservation_id:
        reservation = await db.get(Reservation, payment.reservation_id)
        if reservation is not None and reservation.status == ReservationStatus.AWAITING_PAYMENT:
            reservation.status = ReservationStatus.PAYMENT_AUTHORIZED

    try:
        await db.commit()
        await db.refresh(payment)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="PAYMENT_AUTHORIZE_FAILED") from exc

    return {"data": {"payment": serialize_payment_for_user(payment)}}


@yookassa_webhook_router.post("/yookassa")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    from backend.utils.yookassa_service import verify_yookassa_notification

    if not verify_yookassa_notification(request):
        raise HTTPException(status_code=401, detail="INVALID_WEBHOOK_SIGNATURE")

    try:
        raw = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="INVALID_WEBHOOK_PAYLOAD") from exc

    try:
        body = YooKassaWebhookBody.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="INVALID_WEBHOOK_PAYLOAD") from exc

    event = body.event
    oid = body.object_id()
    ostatus = body.object_status()

    try:
        await process_yookassa_webhook(
            db,
            event=event,
            object_id=oid,
            object_status=ostatus,
            raw_payload=raw if isinstance(raw, dict) else {},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PAYMENT_WEBHOOK_FAILED") from exc

    return {"data": {"accepted": True}}
