"""Тесты сверки платежей с ЮKassa.

Сценарий бага (жалоба 2026-08-19): клиент оплатил бронь 40 минут назад,
деньги списаны, а сайт продолжал показывать «Оплатить» и таймер «До отмены
брони». Причина — статус платежа в нашей БД оставался PENDING: уведомление
ЮKassa отбрасывалось проверкой Basic-авторизации (которой у ЮKassa нет), а
поллинг статуса делала только страница /payment/return, куда клиент после
оплаты через СБП не возвращался.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

TEST_DB_PATH = os.path.abspath(
    f"./backend/tests/test_payment_reconcile_{uuid4().hex}.sqlite"
)
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
os.environ["ESI_DEV_STUB"] = "true"
os.environ["UPLOAD_DEV_STUB"] = "true"

from backend.main import app  # noqa: E402,F401  (регистрирует модели в metadata)
from backend.core.database import Base, SessionLocal, engine  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    PaymentStatus,
    PaymentType,
    ReservationStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.payment import Payment  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils import reservation_expiry, yookassa_service  # noqa: E402
from backend.utils.payment_reconcile import reconcile_pending_payments  # noqa: E402
from backend.utils.reservation_expiry import expire_stale_reservations  # noqa: E402
from backend.utils.reservation_utils import ensure_utc  # noqa: E402


class _FakeYooKassa:
    """Подменяет ответ ЮKassa на заданный статус и считает запросы."""

    def __init__(self, status: str | None):
        self.status = status
        self.calls: list[str] = []

    async def fetch(self, provider_payment_id: str) -> str | None:
        self.calls.append(provider_payment_id)
        return self.status


class PaymentReconcileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        self._original_fetch = yookassa_service.fetch_yookassa_payment_status
        self.refunds: list[str] = []
        self.cancels: list[str] = []

        async def _fake_refund(provider_payment_id, **_kwargs):
            self.refunds.append(provider_payment_id)
            return {"status": "succeeded"}

        async def _fake_cancel(provider_payment_id, **_kwargs):
            self.cancels.append(provider_payment_id)
            return {"status": "canceled"}

        self._original_refund = reservation_expiry.refund_yookassa_payment
        self._original_cancel = reservation_expiry.cancel_yookassa_payment
        reservation_expiry.refund_yookassa_payment = _fake_refund
        reservation_expiry.cancel_yookassa_payment = _fake_cancel

        async with SessionLocal() as db:
            self.city_id = uuid4()
            self.category_id = uuid4()
            self.product_id = uuid4()
            self.plan_id = uuid4()
            self.user_id = uuid4()
            db.add_all(
                [
                    City(
                        id=self.city_id,
                        name="Test City",
                        slug="test-city",
                        timezone="Europe/Moscow",
                        is_active=True,
                        sort_order=0,
                    ),
                    ProductCategory(
                        id=self.category_id,
                        name="Cat",
                        slug="cat",
                        is_active=True,
                        sort_order=0,
                    ),
                    Product(
                        id=self.product_id,
                        category_id=self.category_id,
                        name="Пылесос",
                        slug="pylesos",
                        is_active=True,
                    ),
                    PricePlan(
                        id=self.plan_id,
                        product_id=self.product_id,
                        name="1 day",
                        duration_type="day",
                        duration_value=1,
                        base_amount=Decimal("100.00"),
                        currency="RUB",
                        is_active=True,
                    ),
                    User(
                        id=self.user_id,
                        phone="+79991112233",
                        verification_status=VerificationStatus.APPROVED,
                    ),
                ]
            )
            await db.commit()

    async def asyncTearDown(self):
        yookassa_service.fetch_yookassa_payment_status = self._original_fetch
        reservation_expiry.refund_yookassa_payment = self._original_refund
        reservation_expiry.cancel_yookassa_payment = self._original_cancel
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        try:
            await engine.dispose()
            if os.path.exists(TEST_DB_PATH):
                os.remove(TEST_DB_PATH)
        except (PermissionError, OSError):
            pass

    def _patch_yookassa(self, status: str | None) -> _FakeYooKassa:
        fake = _FakeYooKassa(status)
        yookassa_service.fetch_yookassa_payment_status = fake.fetch
        return fake

    async def _seed(
        self,
        *,
        reservation_status: ReservationStatus,
        payment_status: PaymentStatus,
        created_ago: timedelta,
        expires_in: timedelta,
    ) -> tuple[Reservation, Payment]:
        now = datetime.now(timezone.utc)
        created_at = now - created_ago
        async with SessionLocal() as db:
            locker = LockerLocation(
                id=uuid4(),
                city_id=self.city_id,
                name="ПВЗ Московский",
                address="ул. Тестовая, 1",
                status=LockerStatus.ONLINE,
                external_provider="esi",
                external_locker_id=f"LOCKER-{uuid4().hex[:6]}",
            )
            cell = LockerCell(
                id=uuid4(),
                locker_id=locker.id,
                label="A1",
                external_cell_id="A1",
                status=LockerCellStatus.OCCUPIED,
                supports_return=True,
            )
            unit = InventoryUnit(
                id=uuid4(),
                product_id=self.product_id,
                locker_cell_id=cell.id,
                status=InventoryStatus.RESERVED,
                serial_number=f"SN-{uuid4().hex[:6]}",
            )
            reservation = Reservation(
                id=uuid4(),
                user_id=self.user_id,
                product_id=self.product_id,
                inventory_unit_id=unit.id,
                locker_id=locker.id,
                price_plan_id=self.plan_id,
                status=reservation_status,
                duration_type="day",
                duration_value=1,
                quoted_amount=Decimal("100.00"),
                preauth_amount=Decimal("100.00"),
                expires_at=now + expires_in,
                pickup_at=None,
                created_at=created_at,
                updated_at=created_at,
            )
            payment = Payment(
                id=uuid4(),
                user_id=self.user_id,
                reservation_id=reservation.id,
                provider="yookassa",
                provider_payment_id=f"yk-{uuid4().hex[:10]}",
                type=PaymentType.PREAUTH,
                status=payment_status,
                amount=Decimal("100.00"),
                currency="RUB",
                created_at=created_at,
                updated_at=created_at,
            )
            db.add_all([locker, cell, unit, reservation, payment])
            await db.commit()
            return reservation, payment

    async def _reload(self, reservation_id, payment_id):
        async with SessionLocal() as db:
            return await db.get(Reservation, reservation_id), await db.get(
                Payment, payment_id
            )

    # ── Сверка ────────────────────────────────────────────────────

    async def test_paid_but_pending_payment_is_recovered(self):
        """Главный кейс: деньги списаны, у нас PENDING — sweep чинит бронь."""
        reservation, payment = await self._seed(
            reservation_status=ReservationStatus.AWAITING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            created_ago=timedelta(minutes=40),
            expires_in=timedelta(hours=1, minutes=20),
        )
        fake = self._patch_yookassa("succeeded")

        await reconcile_pending_payments()

        self.assertEqual(fake.calls, [payment.provider_payment_id])
        refreshed, refreshed_payment = await self._reload(reservation.id, payment.id)
        self.assertEqual(refreshed_payment.status, PaymentStatus.CAPTURED)
        self.assertIsNotNone(refreshed_payment.processed_at)
        self.assertEqual(refreshed.status, ReservationStatus.PAYMENT_AUTHORIZED)
        # Срок жизни продлён с окна оплаты до конца дня выдачи.
        self.assertGreater(
            ensure_utc(refreshed.expires_at),
            datetime.now(timezone.utc) + timedelta(hours=2),
        )

    async def test_still_pending_payment_is_left_alone(self):
        reservation, payment = await self._seed(
            reservation_status=ReservationStatus.AWAITING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            created_ago=timedelta(minutes=40),
            expires_in=timedelta(hours=1),
        )
        self._patch_yookassa("pending")

        await reconcile_pending_payments()

        refreshed, refreshed_payment = await self._reload(reservation.id, payment.id)
        self.assertEqual(refreshed_payment.status, PaymentStatus.PENDING)
        self.assertEqual(refreshed.status, ReservationStatus.AWAITING_PAYMENT)

    async def test_fresh_payment_is_not_polled(self):
        """Свежий платёж закрывает сама страница возврата — не дёргаем API."""
        await self._seed(
            reservation_status=ReservationStatus.AWAITING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            created_ago=timedelta(seconds=5),
            expires_in=timedelta(hours=2),
        )
        fake = self._patch_yookassa("succeeded")

        await reconcile_pending_payments()

        self.assertEqual(fake.calls, [])

    async def test_provider_unreachable_keeps_status(self):
        reservation, payment = await self._seed(
            reservation_status=ReservationStatus.AWAITING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            created_ago=timedelta(minutes=40),
            expires_in=timedelta(hours=1),
        )
        self._patch_yookassa(None)

        await reconcile_pending_payments()

        refreshed, refreshed_payment = await self._reload(reservation.id, payment.id)
        self.assertEqual(refreshed_payment.status, PaymentStatus.PENDING)
        self.assertEqual(refreshed.status, ReservationStatus.AWAITING_PAYMENT)

    async def test_second_payment_is_blocked_when_first_already_succeeded(self):
        """Клиент жмёт «Оплатить» на уже оплаченной брони — второй раз не берём."""
        from fastapi import HTTPException

        from backend.utils.payment_flow import (
            ensure_no_active_payment_for_reservation,
        )

        reservation, payment = await self._seed(
            reservation_status=ReservationStatus.AWAITING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            created_ago=timedelta(minutes=40),
            expires_in=timedelta(hours=1, minutes=20),
        )
        self._patch_yookassa("succeeded")

        async with SessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await ensure_no_active_payment_for_reservation(db, reservation.id)
        self.assertEqual(ctx.exception.detail, "PAYMENT_ALREADY_EXISTS")

        refreshed, refreshed_payment = await self._reload(reservation.id, payment.id)
        self.assertEqual(refreshed_payment.status, PaymentStatus.CAPTURED)
        self.assertEqual(refreshed.status, ReservationStatus.PAYMENT_AUTHORIZED)

    # ── Экспирация ────────────────────────────────────────────────

    async def test_expiry_does_not_kill_actually_paid_reservation(self):
        """Бронь «неоплачена» и просрочена, но деньги списаны — не хороним."""
        reservation, payment = await self._seed(
            reservation_status=ReservationStatus.AWAITING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            created_ago=timedelta(hours=2, minutes=5),
            expires_in=timedelta(minutes=-5),
        )
        self._patch_yookassa("succeeded")

        await expire_stale_reservations()

        refreshed, refreshed_payment = await self._reload(reservation.id, payment.id)
        self.assertEqual(refreshed_payment.status, PaymentStatus.CAPTURED)
        self.assertEqual(refreshed.status, ReservationStatus.PAYMENT_AUTHORIZED)
        self.assertGreater(ensure_utc(refreshed.expires_at), datetime.now(timezone.utc))
        self.assertEqual(self.refunds, [])

    async def test_expiry_of_unpaid_reservation_still_works(self):
        reservation, payment = await self._seed(
            reservation_status=ReservationStatus.AWAITING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            created_ago=timedelta(hours=2, minutes=5),
            expires_in=timedelta(minutes=-5),
        )
        self._patch_yookassa("canceled")

        await expire_stale_reservations()

        refreshed, _ = await self._reload(reservation.id, payment.id)
        self.assertEqual(refreshed.status, ReservationStatus.EXPIRED)
        async with SessionLocal() as db:
            unit = await db.get(InventoryUnit, refreshed.inventory_unit_id)
        self.assertEqual(unit.status, InventoryStatus.AVAILABLE)

    async def test_expiry_refunds_captured_payment(self):
        """Одностадийная оплата: при экспирации деньги надо вернуть, не cancel."""
        reservation, payment = await self._seed(
            reservation_status=ReservationStatus.PAYMENT_AUTHORIZED,
            payment_status=PaymentStatus.CAPTURED,
            created_ago=timedelta(days=2),
            expires_in=timedelta(minutes=-5),
        )
        self._patch_yookassa("succeeded")

        await expire_stale_reservations()

        refreshed, refreshed_payment = await self._reload(reservation.id, payment.id)
        self.assertEqual(refreshed.status, ReservationStatus.EXPIRED)
        self.assertEqual(self.refunds, [payment.provider_payment_id])
        self.assertEqual(self.cancels, [])
        self.assertEqual(refreshed_payment.status, PaymentStatus.REFUNDED)

    async def test_expiry_waits_when_refund_fails(self):
        """Возврат не прошёл — бронь не закрываем, повторим на следующем тике."""

        async def _broken_refund(*_args, **_kwargs):
            raise RuntimeError("YooKassa 500")

        reservation, payment = await self._seed(
            reservation_status=ReservationStatus.PAYMENT_AUTHORIZED,
            payment_status=PaymentStatus.CAPTURED,
            created_ago=timedelta(days=2),
            expires_in=timedelta(minutes=-5),
        )
        self._patch_yookassa("succeeded")
        reservation_expiry.refund_yookassa_payment = _broken_refund

        await expire_stale_reservations()

        refreshed, refreshed_payment = await self._reload(reservation.id, payment.id)
        self.assertEqual(refreshed.status, ReservationStatus.PAYMENT_AUTHORIZED)
        self.assertEqual(refreshed_payment.status, PaymentStatus.CAPTURED)

    async def test_expiry_cancels_authorized_hold(self):
        reservation, payment = await self._seed(
            reservation_status=ReservationStatus.PAYMENT_AUTHORIZED,
            payment_status=PaymentStatus.AUTHORIZED,
            created_ago=timedelta(days=2),
            expires_in=timedelta(minutes=-5),
        )
        self._patch_yookassa("waiting_for_capture")

        await expire_stale_reservations()

        refreshed, refreshed_payment = await self._reload(reservation.id, payment.id)
        self.assertEqual(refreshed.status, ReservationStatus.EXPIRED)
        self.assertEqual(self.cancels, [payment.provider_payment_id])
        self.assertEqual(self.refunds, [])
        self.assertEqual(refreshed_payment.status, PaymentStatus.CANCELLED)


class YooKassaNotificationSourceTests(unittest.TestCase):
    """IP-проверка уведомлений вместо несуществующей Basic-авторизации."""

    class _Request:
        def __init__(self, headers: dict[str, str], client_host: str | None):
            self.headers = headers
            self.client = (
                type("C", (), {"host": client_host})() if client_host else None
            )

    def test_official_subnet_is_trusted(self):
        request = self._Request({"X-Forwarded-For": "185.71.76.5"}, "10.0.0.2")
        self.assertTrue(yookassa_service.is_yookassa_notification_ip(request))

    def test_spoofed_forwarded_for_is_not_trusted(self):
        # Caddy дописывает реальный адрес пира в конец — читаем последний.
        request = self._Request(
            {"X-Forwarded-For": "185.71.76.5, 203.0.113.7"}, "10.0.0.2"
        )
        self.assertFalse(yookassa_service.is_yookassa_notification_ip(request))

    def test_random_ip_is_not_trusted(self):
        request = self._Request({}, "203.0.113.7")
        self.assertFalse(yookassa_service.is_yookassa_notification_ip(request))

    def test_ipv6_subnet_is_trusted(self):
        request = self._Request({"X-Forwarded-For": "2a02:5180::1"}, None)
        self.assertTrue(yookassa_service.is_yookassa_notification_ip(request))


if __name__ == "__main__":
    unittest.main()
