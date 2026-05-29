"""Тесты одностадийной оплаты YooKassa и возврата.

Покрытие:
- stub create возвращает pending + confirmation_url (флаг dev-stub);
- stub refund возвращает succeeded, не требуя сети;
- webhook со статусом succeeded (CAPTURED) переводит бронь в
  PAYMENT_AUTHORIZED (одностадийная схема).
"""

from __future__ import annotations

import os
import unittest
from decimal import Decimal
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("UPLOAD_DEV_STUB", "true")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.core.settings import settings
from backend.models.city import City
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    PaymentStatus,
    PaymentType,
    ReservationStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.payment import Payment
from backend.models.payment_event import PaymentEvent
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.reservation import Reservation
from backend.models.user import User
from backend.utils.payment_flow import process_yookassa_webhook
from backend.utils.yookassa_service import (
    cancel_yookassa_payment,
    create_yookassa_preauth_payment,
    refund_yookassa_payment,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

TEST_TABLES = [
    City.__table__,
    ProductCategory.__table__,
    Product.__table__,
    User.__table__,
    LockerLocation.__table__,
    LockerCell.__table__,
    InventoryUnit.__table__,
    PricePlan.__table__,
    Reservation.__table__,
    Payment.__table__,
    PaymentEvent.__table__,
]


class YookassaStubServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_stub = settings.YOOKASSA_DEV_STUB
        settings.YOOKASSA_DEV_STUB = True

    def tearDown(self) -> None:
        settings.YOOKASSA_DEV_STUB = self._old_stub

    async def test_stub_create_returns_pending_with_confirmation(self) -> None:
        out = await create_yookassa_preauth_payment(
            amount_value=Decimal("590.00"),
            currency="RUB",
            return_url="https://naprokatberu.ru/payment/return",
            metadata={"x": "y"},
        )
        self.assertEqual(out["status"], "pending")
        self.assertTrue(out["provider_payment_id"].startswith("stub-"))
        self.assertEqual(out["confirmation_url"], "https://naprokatberu.ru/payment/return")

    async def test_stub_refund_succeeds(self) -> None:
        out = await refund_yookassa_payment(
            "stub-123", amount_value=Decimal("590.00"), currency="RUB"
        )
        self.assertEqual(out["status"], "succeeded")
        self.assertIn("refund_id", out)

    async def test_stub_cancel_succeeds(self) -> None:
        out = await cancel_yookassa_payment("stub-123")
        self.assertEqual(out["status"], "canceled")


class YookassaWebhookCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(TEST_DB_URL, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(c, tables=TEST_TABLES)
            )
        self.SessionLocal = async_sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _seed_awaiting_payment(self):
        async with self.SessionLocal() as db:
            city = City(id=uuid4(), name="C", slug="c", timezone="Europe/Moscow", is_active=True, sort_order=0)
            cat = ProductCategory(id=uuid4(), name="K", slug="k", is_active=True, sort_order=0)
            prod = Product(id=uuid4(), category_id=cat.id, name="P", slug="p", is_active=True)
            user = User(id=uuid4(), phone="+79990000001", verification_status=VerificationStatus.APPROVED)
            loc = LockerLocation(id=uuid4(), city_id=city.id, name="L", address="A", status=LockerStatus.ONLINE, external_provider="esi", external_locker_id="PST_X")
            cell = LockerCell(id=uuid4(), locker_id=loc.id, label="A1", external_cell_id="1", status=LockerCellStatus.RESERVED, supports_return=True)
            unit = InventoryUnit(id=uuid4(), product_id=prod.id, locker_cell_id=cell.id, status=InventoryStatus.RESERVED, serial_number="S1")
            plan = PricePlan(id=uuid4(), product_id=prod.id, name="1 день", duration_type="day", duration_value=1, base_amount=590, currency="RUB", is_active=True, sort_order=0)
            from datetime import datetime, timedelta, timezone
            res = Reservation(
                id=uuid4(), user_id=user.id, product_id=prod.id, inventory_unit_id=unit.id,
                locker_id=loc.id, price_plan_id=plan.id, status=ReservationStatus.AWAITING_PAYMENT,
                duration_type="day", duration_value=1, quoted_amount=Decimal("590.00"),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            payment = Payment(
                id=uuid4(), user_id=user.id, reservation_id=res.id, provider="yookassa",
                provider_payment_id="yk-test-1", type=PaymentType.PREAUTH,
                status=PaymentStatus.PENDING, amount=Decimal("590.00"), currency="RUB",
            )
            db.add_all([city, cat, prod, user, loc, cell, unit, plan, res, payment])
            await db.commit()
            return {"res_id": res.id, "payment_id": payment.id}

    async def test_succeeded_webhook_captures_and_authorizes_reservation(self) -> None:
        ids = await self._seed_awaiting_payment()
        async with self.SessionLocal() as db:
            await process_yookassa_webhook(
                db,
                event="payment.succeeded",
                object_id="yk-test-1",
                object_status="succeeded",
                raw_payload={"event": "payment.succeeded"},
            )
        async with self.SessionLocal() as db:
            payment = await db.get(Payment, ids["payment_id"])
            res = await db.get(Reservation, ids["res_id"])
        self.assertEqual(payment.status, PaymentStatus.CAPTURED)
        self.assertEqual(res.status, ReservationStatus.PAYMENT_AUTHORIZED)


if __name__ == "__main__":
    unittest.main()
