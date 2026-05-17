from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.schemas.esi_webhook_schemas import EsiWebhookPayload
from backend.utils.esi_webhook_handler import process_esi_webhook_payload, verify_esi_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/esi")
async def esi_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    import json

    body = await request.body()
    sig = request.headers.get("X-ESI-Signature")
    if not verify_esi_signature(body, sig):
        raise HTTPException(status_code=401, detail="INVALID_ESI_SIGNATURE")

    try:
        raw = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="INVALID_ESI_PAYLOAD") from exc

    try:
        payload = EsiWebhookPayload.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="INVALID_ESI_PAYLOAD") from exc

    try:
        await process_esi_webhook_payload(
            db,
            payload=payload.model_dump(exclude_none=True),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="ESI_WEBHOOK_FAILED") from exc

    return {"data": {"accepted": True}}
