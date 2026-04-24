from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.reservation import Reservation
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

    out = await create_preauth_for_reservation(db, user=user, reservation=reservation)
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
