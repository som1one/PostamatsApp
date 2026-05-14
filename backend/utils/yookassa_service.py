import asyncio
import base64
import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import Request

from backend.core.settings import settings

logger = logging.getLogger(__name__)


def verify_yookassa_notification(request: Request) -> bool:
    if settings.YOOKASSA_DEV_STUB and not settings.YOOKASSA_SECRET_KEY:
        return True
    shop_id = settings.YOOKASSA_SHOP_ID
    secret = settings.YOOKASSA_SECRET_KEY
    if not shop_id or not secret:
        return False
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:].strip()).decode("utf-8")
        user, _, pwd = raw.partition(":")
        return user == shop_id and pwd == secret
    except Exception:
        return False


def _create_payment_sync(
    *,
    amount_value: Decimal,
    currency: str,
    return_url: str,
    metadata: dict[str, str],
) -> dict[str, Any]:
    from yookassa import Configuration, Payment

    Configuration.configure(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)

    value_str = format(amount_value.quantize(Decimal("0.01")), "f")
    body: dict[str, Any] = {
        "amount": {"value": value_str, "currency": currency},
        "capture": False,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "metadata": metadata,
        "description": "Бронирование: предавторизация",
    }
    idempotency_key = str(uuid.uuid4())
    payment = Payment.create(body, idempotency_key)
    conf = payment.confirmation
    confirmation_url = getattr(conf, "confirmation_url", None) if conf else None
    return {
        "provider_payment_id": payment.id,
        "status": payment.status,
        "confirmation_type": getattr(conf, "type", "redirect") if conf else "redirect",
        "confirmation_url": confirmation_url,
    }


def _cancel_payment_sync(provider_payment_id: str) -> dict[str, Any]:
    from yookassa import Configuration, Payment

    Configuration.configure(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)
    idempotency_key = str(uuid.uuid4())
    payment = Payment.cancel(provider_payment_id, idempotency_key)
    return {"status": payment.status}


async def cancel_yookassa_payment(provider_payment_id: str) -> dict[str, Any]:
    if settings.YOOKASSA_DEV_STUB:
        return {"status": "canceled"}
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise RuntimeError("YooKassa is not configured")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _cancel_payment_sync(provider_payment_id),
    )


async def create_yookassa_preauth_payment(
    *,
    amount_value: Decimal,
    currency: str,
    return_url: str,
    metadata: dict[str, str],
) -> dict[str, Any]:
    if settings.YOOKASSA_DEV_STUB:
        fake_id = f"stub-{uuid.uuid4()}"
        return {
            "provider_payment_id": fake_id,
            "status": "pending",
            "confirmation_type": "redirect",
            "confirmation_url": return_url or "https://example.com/yookassa-stub-return",
        }
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise RuntimeError("YooKassa is not configured")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _create_payment_sync(
            amount_value=amount_value,
            currency=currency,
            return_url=return_url or "https://example.com/payment-return",
            metadata=metadata,
        ),
    )
