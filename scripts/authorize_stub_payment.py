from __future__ import annotations

import argparse
import json
from importlib import import_module
from pathlib import Path
import sys

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.settings import settings
from backend.models.enums import PaymentStatus, PaymentType
from backend.models.payment import Payment
from backend.models.user import User
from backend.utils.phone_utils import normalize_phone_for_storage


MODEL_MODULES = (
    "backend.models.admin_account",
    "backend.models.admin_audit_event",
    "backend.models.admin_auth_session",
    "backend.models.admin_user",
    "backend.models.auth_session",
    "backend.models.auth_verification_session",
    "backend.models.city",
    "backend.models.condition_report",
    "backend.models.condition_report_photo",
    "backend.models.featured_product_state",
    "backend.models.inventory_movement",
    "backend.models.inventory_unit",
    "backend.models.locker_cell",
    "backend.models.locker_location",
    "backend.models.media_file",
    "backend.models.payment",
    "backend.models.payment_event",
    "backend.models.price_plan",
    "backend.models.product",
    "backend.models.product_filter",
    "backend.models.product_category",
    "backend.models.product_image",
    "backend.models.rental",
    "backend.models.rental_event",
    "backend.models.reservation",
    "backend.models.user",
    "backend.models.verification_request",
)


def load_models() -> None:
    for module_name in MODEL_MODULES:
        import_module(module_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Authorize the latest pending YooKassa stub payment for a test user.",
    )
    parser.add_argument(
        "--phone",
        required=True,
        help="Phone number of the test user, e.g. +79990001234",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8010",
        help="Backend base URL. Default: http://127.0.0.1:8010",
    )
    return parser


def find_latest_pending_payment(phone: str) -> tuple[str, str, str]:
    if not settings.DB_URL:
        raise RuntimeError("DB_URL is not configured")

    normalized_phone = normalize_phone_for_storage(phone)
    engine = create_engine(settings.DB_URL)

    with Session(engine) as session:
        user = session.execute(select(User).where(User.phone == normalized_phone)).scalar_one_or_none()
        if user is None:
            raise RuntimeError(f"User not found for phone {normalized_phone}")

        payment = session.execute(
            select(Payment)
            .where(
                Payment.user_id == user.id,
                Payment.type == PaymentType.PREAUTH,
                Payment.status == PaymentStatus.PENDING,
            )
            .order_by(Payment.created_at.desc())
        ).scalars().first()
        if payment is None:
            raise RuntimeError(
                f"No pending preauth payment found for phone {normalized_phone}"
            )

        # Detach values before session closes.
        return user.phone, str(payment.id), str(payment.provider_payment_id)


def main() -> None:
    load_models()
    args = build_parser().parse_args()
    user_phone, payment_id, provider_payment_id = find_latest_pending_payment(args.phone)

    if not provider_payment_id:
        raise RuntimeError(
            f"Payment {payment_id} does not have provider_payment_id yet"
        )

    payload = {
            "type": "notification",
            "event": "payment.waiting_for_capture",
            "object": {
            "id": provider_payment_id,
            "status": "waiting_for_capture",
        },
    }

    response = httpx.post(
        f"{args.base_url.rstrip('/')}/payments/webhooks/yookassa",
        json=payload,
        timeout=15,
    )
    response.raise_for_status()

    print(
        json.dumps(
            {
                "ok": True,
                "phone": user_phone,
                "paymentId": payment_id,
                "providerPaymentId": provider_payment_id,
                "webhookResponse": response.json(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
