"""Тесты экспирации забора (backend/utils/rental_pickup_expiry.py).

Клиент оплатил, но не получил PIN до `pickup_expires_at` — шедулер отменяет
аренду. Ключевое требование: деньги при этом возвращаются. Раньше проход
просто закрывал аренду, и клиент оставался и без товара, и без денег.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

# DSN и стабы перекрываем ДО импорта приложения (как в остальных тестах).
TEST_DB_PATH = os.path.abspath(
    f"./backend/tests/test_pickup_expiry_{uuid4().hex}.sqlite"
)
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
os.environ["ESI_DEV_STUB"] = "true"
os.environ["UPLOAD_DEV_STUB"] = "true"

from sqlalchemy import select  # noqa: E402

from backend.main import app  # noqa: E402,F401  (регистрирует все модели в metadata)
from backend.core.database import Base, SessionLocal, engine  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    PaymentStatus,
    PaymentType,
    RentalStatus,
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
from backend.models.rental import Rental  # noqa: E402
from backend.models.rental_event import RentalEvent  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.rental_pickup_expiry import expire_stale_pickup_rentals  # noqa: E402


class RentalPickupExpiryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        self.city_id = uuid4()
        self.category_id = uuid4()
        self.product_id = uuid4()
        self.plan_id = uuid4()
        self.user_id = uuid4()

        async with SessionLocal() as db:
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
                        name="Perforator",
                        slug="perforator",
                        is_active=True,
                    ),
                    PricePlan(
                        id=self.plan_id,
                        product_id=self.product_id,
                        name="1 day",
                        duration_type="day",
                        duration_value=1,
                        base_amount=Decimal("1120.00"),
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
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        try:
            await engine.dispose()
            if os.path.exists(TEST_DB_PATH):
                os.remove(TEST_DB_PATH)
        except (PermissionError, OSError):
            pass

    async def _seed_rental(
        self,
        *,
        pickup_expires_in: timedelta,
        payment_status: PaymentStatus | None = PaymentStatus.CAPTURED,
    ) -> Rental:
        """Оплаченная аренда в PICKUP_READY с товаром в зарезервированной ячейке."""

        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            locker = LockerLocation(
                id=uuid4(),
                city_id=self.city_id,
                name="Locker",
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
                status=LockerCellStatus.RESERVED,
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
                status=ReservationStatus.CONFIRMED,
                duration_type="day",
                duration_value=1,
                quoted_amount=Decimal("1120.00"),
                preauth_amount=Decimal("1120.00"),
                expires_at=now + timedelta(hours=2),
                pickup_at=now - timedelta(hours=10),
            )
            rental = Rental(
                id=uuid4(),
                user_id=self.user_id,
                reservation_id=reservation.id,
                inventory_unit_id=unit.id,
                pickup_locker_id=locker.id,
                status=RentalStatus.PICKUP_READY,
                pickup_pin="1234",
                pickup_expires_at=now + pickup_expires_in,
                starts_at=now - timedelta(hours=10),
                planned_end_at=now + timedelta(hours=14),
            )
            db.add_all([locker, cell, unit, reservation, rental])
            if payment_status is not None:
                db.add(
                    Payment(
                        id=uuid4(),
                        user_id=self.user_id,
                        reservation_id=reservation.id,
                        provider="yookassa",
                        provider_payment_id=f"yk-{uuid4().hex[:8]}",
                        type=PaymentType.PREAUTH,
                        status=payment_status,
                        amount=Decimal("1120.00"),
                        currency="RUB",
                    )
                )
            await db.commit()
            self.cell_id = cell.id
            self.unit_id = unit.id
            self.reservation_id = reservation.id
            return rental

    async def _reload(self, rental_id):
        async with SessionLocal() as db:
            rental = await db.get(Rental, rental_id)
            unit = await db.get(InventoryUnit, self.unit_id)
            cell = await db.get(LockerCell, self.cell_id)
            payment = (
                await db.scalars(
                    select(Payment).where(Payment.reservation_id == self.reservation_id)
                )
            ).first()
            events = list(
                (
                    await db.scalars(
                        select(RentalEvent).where(
                            RentalEvent.rental_id == rental_id,
                            RentalEvent.event_type == "pickup_expired",
                        )
                    )
                ).all()
            )
            return rental, unit, cell, payment, events

    async def test_expired_pickup_refunds_captured_payment(self):
        """Деньги списаны (одностадийная оплата) → refund и отмена аренды."""

        rental = await self._seed_rental(pickup_expires_in=timedelta(minutes=-1))

        with patch(
            "backend.utils.payment_flow.refund_yookassa_payment", new=AsyncMock()
        ) as refund, patch(
            "backend.utils.payment_flow.cancel_yookassa_payment", new=AsyncMock()
        ) as cancel:
            await expire_stale_pickup_rentals()

        refund.assert_awaited_once()
        cancel.assert_not_awaited()
        self.assertEqual(refund.await_args.kwargs["amount_value"], Decimal("1120.00"))

        updated, unit, cell, payment, events = await self._reload(rental.id)
        self.assertEqual(updated.status, RentalStatus.CANCELLED)
        self.assertEqual(updated.cancel_reason, "pickup_expired")
        self.assertIsNotNone(updated.actual_end_at)
        self.assertEqual(payment.status, PaymentStatus.REFUNDED)
        self.assertIsNotNone(payment.processed_at)
        self.assertEqual(unit.status, InventoryStatus.AVAILABLE)
        self.assertEqual(cell.status, LockerCellStatus.VACANT)
        self.assertEqual(len(events), 1)

    async def test_expired_pickup_cancels_authorized_hold(self):
        """Двухстадийная схема: холд снимаем через cancel, а не refund."""

        rental = await self._seed_rental(
            pickup_expires_in=timedelta(minutes=-1),
            payment_status=PaymentStatus.AUTHORIZED,
        )

        with patch(
            "backend.utils.payment_flow.refund_yookassa_payment", new=AsyncMock()
        ) as refund, patch(
            "backend.utils.payment_flow.cancel_yookassa_payment", new=AsyncMock()
        ) as cancel:
            await expire_stale_pickup_rentals()

        cancel.assert_awaited_once()
        refund.assert_not_awaited()

        updated, _unit, _cell, payment, _events = await self._reload(rental.id)
        self.assertEqual(updated.status, RentalStatus.CANCELLED)
        self.assertEqual(payment.status, PaymentStatus.CANCELLED)

    async def test_rental_survives_when_refund_fails(self):
        """ЮKassa недоступна — аренду не закрываем, повторим на следующем тике.

        Держать товар в ячейке дешевле, чем оставить клиента без вещи и
        без денег.
        """

        rental = await self._seed_rental(pickup_expires_in=timedelta(minutes=-1))

        with patch(
            "backend.utils.payment_flow.refund_yookassa_payment",
            new=AsyncMock(side_effect=RuntimeError("yookassa is down")),
        ):
            await expire_stale_pickup_rentals()

        updated, unit, cell, payment, events = await self._reload(rental.id)
        self.assertEqual(updated.status, RentalStatus.PICKUP_READY)
        self.assertIsNone(updated.cancel_reason)
        self.assertEqual(payment.status, PaymentStatus.CAPTURED)
        self.assertEqual(unit.status, InventoryStatus.RESERVED)
        self.assertEqual(cell.status, LockerCellStatus.RESERVED)
        self.assertEqual(events, [])

    async def test_pickup_still_in_window_is_left_alone(self):
        """Срок забора не истёк — ни отмены, ни возврата."""

        rental = await self._seed_rental(pickup_expires_in=timedelta(hours=3))

        with patch(
            "backend.utils.payment_flow.refund_yookassa_payment", new=AsyncMock()
        ) as refund:
            await expire_stale_pickup_rentals()

        refund.assert_not_awaited()

        updated, unit, _cell, payment, events = await self._reload(rental.id)
        self.assertEqual(updated.status, RentalStatus.PICKUP_READY)
        self.assertEqual(payment.status, PaymentStatus.CAPTURED)
        self.assertEqual(unit.status, InventoryStatus.RESERVED)
        self.assertEqual(events, [])

    async def test_rental_without_payment_is_still_cancelled(self):
        """Платежа нет (например, ручная выдача) — просто отменяем аренду."""

        rental = await self._seed_rental(
            pickup_expires_in=timedelta(minutes=-1),
            payment_status=None,
        )

        with patch(
            "backend.utils.payment_flow.refund_yookassa_payment", new=AsyncMock()
        ) as refund:
            await expire_stale_pickup_rentals()

        refund.assert_not_awaited()

        updated, unit, _cell, _payment, events = await self._reload(rental.id)
        self.assertEqual(updated.status, RentalStatus.CANCELLED)
        self.assertEqual(updated.cancel_reason, "pickup_expired")
        self.assertEqual(unit.status, InventoryStatus.AVAILABLE)
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
