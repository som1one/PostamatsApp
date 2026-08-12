"""Тесты фонового авто-confirm оплаченных броней.

Сценарий бага: пользователь оплатил бронь, но /payment/return не отработал
(возврат из приложения банка в другой браузер) — бронь застряла в
PAYMENT_AUTHORIZED и раньше отменялась шедулером через 2 часа после
создания с возвратом холда. Sweep должен продлить бронь до конца дня
выдачи и превратить её в аренду PICKUP_READY.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

# DSN и стабы перекрываем ДО импорта приложения (как в test_full_flow_e2e).
TEST_DB_PATH = os.path.abspath(
    f"./backend/tests/test_auto_confirm_{uuid4().hex}.sqlite"
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
    RentalStatus,
    ReservationStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.rental import Rental  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.reservation_auto_confirm import (  # noqa: E402
    auto_confirm_paid_reservations,
)
from backend.utils.reservation_expiry import expire_stale_reservations  # noqa: E402

MSK = timezone(timedelta(hours=3))


def _utc(value: datetime) -> datetime:
    """SQLite возвращает naive datetime — нормализуем для сравнения."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ReservationAutoConfirmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Файл БД один на прогон (Windows держит lock между тестами),
        # чистим содержимое через drop_all/create_all.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

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
                        name="Karaoke",
                        slug="karaoke",
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
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        try:
            await engine.dispose()
            if os.path.exists(TEST_DB_PATH):
                os.remove(TEST_DB_PATH)
        except (PermissionError, OSError):
            pass

    async def _seed_locker_unit(
        self, *, locker_status: LockerStatus
    ) -> tuple[object, object]:
        """Постамат + ячейка + инвентарь под одну бронь."""
        async with SessionLocal() as db:
            locker = LockerLocation(
                id=uuid4(),
                city_id=self.city_id,
                name="Locker",
                address="ул. Тестовая, 1",
                status=locker_status,
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
            db.add_all([locker, cell, unit])
            await db.commit()
            return locker, unit

    async def _seed_paid_reservation(
        self,
        *,
        locker_id,
        unit_id,
        created_ago: timedelta,
        pickup_at: datetime | None,
    ) -> Reservation:
        now = datetime.now(timezone.utc)
        created_at = now - created_ago
        async with SessionLocal() as db:
            reservation = Reservation(
                id=uuid4(),
                user_id=self.user_id,
                product_id=self.product_id,
                inventory_unit_id=unit_id,
                locker_id=locker_id,
                price_plan_id=self.plan_id,
                status=ReservationStatus.PAYMENT_AUTHORIZED,
                duration_type="day",
                duration_value=1,
                quoted_amount=Decimal("100.00"),
                preauth_amount=Decimal("100.00"),
                # Окно оплаты: создание + 2 часа (как на проде).
                expires_at=created_at + timedelta(hours=2),
                pickup_at=pickup_at,
                created_at=created_at,
                updated_at=created_at,
            )
            db.add(reservation)
            await db.commit()
            return reservation

    async def _get_reservation(self, reservation_id) -> Reservation:
        async with SessionLocal() as db:
            return await db.get(Reservation, reservation_id)

    async def _get_rental_for(self, reservation_id) -> Rental | None:
        async with SessionLocal() as db:
            return (
                await db.scalars(
                    select(Rental).where(Rental.reservation_id == reservation_id)
                )
            ).first()

    async def test_stuck_paid_reservation_is_rescued(self):
        """Кейс бага: оплатили 2 часа назад, выдача сегодня, confirm не прошёл."""
        now = datetime.now(timezone.utc)
        pickup_at = (
            datetime.now(MSK)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(timezone.utc)
        )
        locker, unit = await self._seed_locker_unit(locker_status=LockerStatus.ONLINE)
        reservation = await self._seed_paid_reservation(
            locker_id=locker.id,
            unit_id=unit.id,
            created_ago=timedelta(hours=2, minutes=5),
            pickup_at=pickup_at,
        )
        # На входе бронь уже «просрочена» по старым правилам.
        self.assertLess(reservation.expires_at, now)

        await auto_confirm_paid_reservations()

        refreshed = await self._get_reservation(reservation.id)
        self.assertEqual(refreshed.status, ReservationStatus.CONFIRMED)
        self.assertIsNotNone(refreshed.confirmed_at)

        rental = await self._get_rental_for(reservation.id)
        self.assertIsNotNone(rental)
        self.assertEqual(rental.status, RentalStatus.PICKUP_READY)
        self.assertEqual(len(rental.pickup_pin), 4)
        self.assertEqual(_utc(rental.starts_at), pickup_at)
        # Выдача «сегодня» (полночь уже прошла) → стандартное окно 3 часа.
        self.assertLess(
            abs(
                (_utc(rental.pickup_expires_at) - (now + timedelta(hours=3))).total_seconds()
            ),
            120,
        )

        # Проход экспирации подтверждённую бронь не трогает.
        await expire_stale_reservations()
        refreshed = await self._get_reservation(reservation.id)
        self.assertEqual(refreshed.status, ReservationStatus.CONFIRMED)

    async def test_offline_locker_extends_but_does_not_confirm(self):
        """Постамат офлайн: бронь продлеваем, confirm ждёт следующего тика."""
        pickup_at = (
            datetime.now(MSK)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(timezone.utc)
        )
        locker, unit = await self._seed_locker_unit(locker_status=LockerStatus.OFFLINE)
        reservation = await self._seed_paid_reservation(
            locker_id=locker.id,
            unit_id=unit.id,
            created_ago=timedelta(hours=2, minutes=5),
            pickup_at=pickup_at,
        )

        await auto_confirm_paid_reservations()

        refreshed = await self._get_reservation(reservation.id)
        self.assertEqual(refreshed.status, ReservationStatus.PAYMENT_AUTHORIZED)
        # expires_at продлён до конца дня выдачи (pickup_at + 24ч).
        expected_deadline = pickup_at + timedelta(hours=24)
        self.assertEqual(_utc(refreshed.expires_at), expected_deadline)
        self.assertIsNone(await self._get_rental_for(reservation.id))

        # Экспирация продлённую оплаченную бронь не отменяет.
        await expire_stale_reservations()
        refreshed = await self._get_reservation(reservation.id)
        self.assertEqual(refreshed.status, ReservationStatus.PAYMENT_AUTHORIZED)

    async def test_fresh_reservation_left_for_frontend_confirm(self):
        """Свежая бронь (< 90 сек): фронт сам делает confirm, sweep не лезет."""
        locker, unit = await self._seed_locker_unit(locker_status=LockerStatus.ONLINE)
        reservation = await self._seed_paid_reservation(
            locker_id=locker.id,
            unit_id=unit.id,
            created_ago=timedelta(seconds=10),
            pickup_at=None,
        )
        original_expires = reservation.expires_at

        await auto_confirm_paid_reservations()

        refreshed = await self._get_reservation(reservation.id)
        self.assertEqual(refreshed.status, ReservationStatus.PAYMENT_AUTHORIZED)
        self.assertEqual(_utc(refreshed.expires_at), _utc(original_expires))
        self.assertIsNone(await self._get_rental_for(reservation.id))


if __name__ == "__main__":
    unittest.main()
