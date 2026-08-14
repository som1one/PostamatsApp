"""Боевая проверка ЮKassa напрямую через SDK, минуя наш yookassa_service.

Нужна, чтобы отделить «магазин/чек настроены неправильно» от «наш код
собирает запрос не так»: здесь запрос уходит ровно тем телом, которое
описано ниже, вместе с чеком по ФЗ-54. Созданный платёж тут же
отменяется, но это всё равно обращение к боевому API — запускать руками
и осознанно.

Ключи берём из настроек (backend/.env → YOOKASSA_SHOP_ID и
YOOKASSA_SECRET_KEY), а не из литералов в коде: боевой ключ в исходнике
однажды уедет в git и останется в истории навсегда.
"""

import sys
from uuid import uuid4

from yookassa import Configuration, Payment

from backend.core.settings import settings


def _configure() -> None:
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        print(
            "ERROR: не заданы YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY "
            "(backend/.env или переменные окружения)"
        )
        sys.exit(1)

    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY


def test_yookassa():
    _configure()
    print(f"Shop ID: {settings.YOOKASSA_SHOP_ID}")
    print("Создаем платеж...")
    idempotency_key = str(uuid4())

    # С чеком — бэкенд собирает платёж так же, и именно чек чаще всего
    # ломает боевой запрос, если ФЗ-54 в магазине настроен иначе.
    body = {
        "amount": {"value": "10.00", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": "https://ya.ru"},
        "description": "Аренда: оплата",
        "receipt": {
            "customer": {"email": "customer@naprokatberu.ru"},
            "items": [
                {
                    "description": "Аренда",
                    "quantity": "1.00",
                    "amount": {"value": "10.00", "currency": "RUB"},
                    "vat_code": 1,
                    "payment_mode": "full_prepayment",
                    "payment_subject": "service",
                }
            ],
        },
    }

    try:
        payment = Payment.create(body, idempotency_key)
        print(f"SUCCESS! Payment created: {payment.id}")

        print("Canceling payment...")
        cancel_key = str(uuid4())
        try:
            canceled = Payment.cancel(payment.id, cancel_key)
            print(f"SUCCESS! Status after cancel: {canceled.status}")
        except Exception as e:
            print(f"ERROR on cancel: {e}")

    except Exception as e:
        print(f"ERROR on create: {e}")


if __name__ == "__main__":
    test_yookassa()
