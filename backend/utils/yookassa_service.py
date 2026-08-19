import asyncio
import ipaddress
import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import Request

from backend.core.settings import settings

logger = logging.getLogger(__name__)

# ЮKassa не подписывает уведомления и не шлёт Authorization: единственный
# способ узнать отправителя — сверить IP с официальным списком подсетей.
# https://yookassa.ru/developers/using-api/webhooks — «Проверка подлинности».
# Раньше здесь стояла проверка Basic-авторизации shop_id:secret_key, которой
# в уведомлениях нет и не было, поэтому КАЖДОЕ боевое уведомление получало
# 401 и статус платежа в нашей БД не обновлялся.
YOOKASSA_NOTIFICATION_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "185.71.76.0/27",
        "185.71.77.0/27",
        "77.75.153.0/25",
        "77.75.156.11/32",
        "77.75.156.35/32",
        "77.75.154.128/25",
        "2a02:5180::/32",
    )
)


def resolve_client_ip(request: Request) -> str | None:
    """IP непосредственного отправителя запроса.

    За Caddy реальный адрес приходит последним элементом X-Forwarded-For:
    прокси дописывает адрес своего пира в конец списка, поэтому подделать
    последний элемент снаружи нельзя (клиентский XFF окажется левее).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = [item.strip() for item in forwarded.split(",") if item.strip()]
        if parts:
            return parts[-1]
    client = request.client
    return client.host if client is not None else None


def is_yookassa_notification_ip(request: Request) -> bool:
    raw_ip = resolve_client_ip(request)
    if not raw_ip:
        return False
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    return any(ip in network for network in YOOKASSA_NOTIFICATION_NETWORKS)


def verify_yookassa_notification(request: Request) -> bool:
    """True, если уведомление точно пришло из ЮKassa.

    False — не повод отбрасывать уведомление: обработчик всё равно сверяет
    статус платежа напрямую через API, а IP используется только как признак
    доверия к телу запроса (см. routers/payments.py).
    """
    if settings.YOOKASSA_DEV_STUB and not settings.YOOKASSA_SECRET_KEY:
        return True
    return is_yookassa_notification_ip(request)


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


def _find_payment_sync(provider_payment_id: str) -> dict[str, Any]:
    from yookassa import Configuration, Payment

    Configuration.configure(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)
    payment = Payment.find_one(provider_payment_id)
    return {"status": payment.status}


async def fetch_yookassa_payment_status(provider_payment_id: str) -> str | None:
    """Запрашивает актуальный статус платежа напрямую из ЮKassa API.

    Возвращает строку статуса ('pending', 'waiting_for_capture', 'succeeded',
    'canceled') или None если запрос не удался.
    """
    if settings.YOOKASSA_DEV_STUB:
        return None
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        return None
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _find_payment_sync(provider_payment_id),
        )
        return result.get("status")
    except Exception:
        logger.warning("Failed to fetch payment status from YooKassa: %s", provider_payment_id)
        return None
