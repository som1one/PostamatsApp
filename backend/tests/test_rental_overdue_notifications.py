from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("UPLOAD_DEV_STUB", "true")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.models.admin_account import AdminAccount
from backend.models.city import City
from backend.models.enums import (
    InventoryStatus,
    LockerStatus,
    RentalStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.media_file import MediaFile
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.models.user import User
from backend.utils.rental_overdue import (
    SUPPORT_OVERDUE_NOTIFICATION_EVENT,
    notify_support_about_long_overdue_rentals,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

TEST_TABLES = [
    AdminAccount.__table__,
    City.__table__,
    ProductCategory.__table__,
    Product.__table__,
    User.__table__,
    MediaFile.__table__,
    LockerLocation.__table__,
    LockerCell.__table__,
    InventoryUnit.__table__,
    PricePlan.__table__,
    Reservation.__table__,
    Rental.__table__,
    RentalEvent.__table__,
]


class RentalOverdueNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(TEST_DB_URL, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=TEST_TABLES)
            )
        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )
        self.session_patcher = patch(
            "backend.utils.rental_overdue.SessionLocal", self.SessionLocal
        )
        self.session_patcher.start()

    async def asyncTearDown(self) -> None:
        self.session_patcher.stop()
        await self.engine.dispose()

    async def _seed_overdue_rental(self, *, overdue_for: timedelta):
        now = datetime.now(timezone.utc)
        async with self.SessionLocal() as db:
            city = City(
                id=uuid4(),
                name="Saint Petersburg",
                slug="spb",
                timezone="Europe/Moscow",
                is_active=True,
                sort_order=0,
            )
            category = ProductCategory(
                id=uuid4(), name="Photo", slug="photo", is_active=True, sort_order=0
            )
            product = Product(
                id=uuid4(), category_id=category.id, name="Polaroid", slug="polaroid", is_active=True
            )
            user = User(
                id=uuid4(),
                phone="+79990000001",
                verification_status=VerificationStatus.APPROVED,
            )
            locker = LockerLocation(
                id=uuid4(),
                city_id=city.id,
                name="Санкт-Петербург Невский",
                address="Санкт-Петербург, Невский пр., 1",
                status=LockerStatus.ONLINE,
                external_provider="esi",
                external_locker_id="SPB_1",
            )
            unit = InventoryUnit(
                id=uuid4(),
                product_id=product.id,
                status=InventoryStatus.RENTED,
                serial_number="SN-OVERDUE-1",
            )
            overdue_started_at = now - overdue_for
            rental = Rental(
                id=uuid4(),
                user_id=user.id,
                inventory_unit_id=unit.id,
                pickup_locker_id=locker.id,
                status=RentalStatus.OVERDUE,
                starts_at=now - timedelta(days=2),
                planned_end_at=overdue_started_at,
                overdue_started_at=overdue_started_at,
            )
            db.add_all([city, category, product, user, locker, unit, rental])
            await db.commit()
            return rental.id

    async def test_does_not_notify_before_three_hours(self) -> None:
        await self._seed_overdue_rental(overdue_for=timedelta(hours=2, minutes=59))

        notify_mock = AsyncMock()
        with patch("backend.utils.rental_overdue.notify_admins", notify_mock):
            await notify_support_about_long_overdue_rentals()

        notify_mock.assert_not_awaited()

    async def test_notifies_once_after_three_hours(self) -> None:
        rental_id = await self._seed_overdue_rental(
            overdue_for=timedelta(hours=3, minutes=10)
        )

        notify_mock = AsyncMock()
        with patch("backend.utils.rental_overdue.notify_admins", notify_mock):
            await notify_support_about_long_overdue_rentals()
            await notify_support_about_long_overdue_rentals()

        self.assertEqual(notify_mock.await_count, 1)
        text = notify_mock.await_args.args[0]
        self.assertIn("Санкт-Петербург Невский", text)
        self.assertIn("Polaroid", text)

        async with self.SessionLocal() as db:
            events = list(
                (
                    await db.scalars(
                        select(RentalEvent).where(
                            RentalEvent.rental_id == rental_id,
                            RentalEvent.event_type == SUPPORT_OVERDUE_NOTIFICATION_EVENT,
                        )
                    )
                ).all()
            )
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
