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
        # Одностадийная оплата: деньги списываются сразу при подтверждении
        # платежа клиентом (без отдельного шага capture). Возврат денег —
        # через refund.
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "metadata": metadata,
        "description": "Аренда: оплата",
        "receipt": {
            "customer": {"email": "customer@naprokatberu.ru"},
            "items": [
                {
                    "description": "Аренда",
                    "quantity": "1.00",
                    "amount": {"value": value_str, "currency": currency},
                    "vat_code": 1,
                    "payment_mode": "full_prepayment",
                    "payment_subject": "service",
                }
            ],
        },
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


def _refund_payment_sync(
    provider_payment_id: str,
    *,
    amount_value: Decimal,
    currency: str,
) -> dict[str, Any]:
    from yookassa import Configuration, Refund

    Configuration.configure(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)
    value_str = format(amount_value.quantize(Decimal("0.01")), "f")
    body = {
        "payment_id": provider_payment_id,
        "amount": {"value": value_str, "currency": currency},
    }
    idempotency_key = str(uuid.uuid4())
    refund = Refund.create(body, idempotency_key)
    return {"status": getattr(refund, "status", None), "refund_id": getattr(refund, "id", None)}


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


async def refund_yookassa_payment(
    provider_payment_id: str,
    *,
    amount_value: Decimal,
    currency: str = "RUB",
) -> dict[str, Any]:
    """Возврат уже списанных денег (полный возврат на сумму платежа).

    В stub-режиме возвращает успешный фейковый ответ. На реальном ключе
    дёргает YooKassa Refund API.
    """
    if settings.YOOKASSA_DEV_STUB:
        return {"status": "succeeded", "refund_id": f"stub-refund-{uuid.uuid4()}"}
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise RuntimeError("YooKassa is not configured")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _refund_payment_sync(
            provider_payment_id,
            amount_value=amount_value,
            currency=currency,
        ),
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
