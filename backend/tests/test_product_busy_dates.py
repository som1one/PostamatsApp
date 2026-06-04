"""Тесты занятости дат и видимости товара в каталоге.

Проверяем, что:
- compute_busy_dates_for_product помечает занятыми все дни активной
  аренды (по локальному МСК-дню) и активной брони;
- завершённые/отменённые аренды и истёкшие брони не блокируют даты;
- фильтр по lockerId ограничивает занятость одним постаматом;
- aggregate_placed_* видят товар, даже если его единственный юнит
  занят (RESERVED/RENTED), — товар не исчезает из каталога.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("UPLOAD_DEV_STUB", "true")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.models.city import City
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    RentalStatus,
    ReservationStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.rental import Rental
from backend.models.reservation import Reservation
from backend.models.user import User
from backend.routers.reservation import _get_available_inventory_unit
from backend.utils.products_utils import (
    aggregate_placed_globally,
    aggregate_placed_in_city,
    compute_busy_dates_for_product,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

MSK = timezone(timedelta(hours=3))

# Создаём только таблицы, нужные этим тестам, чтобы не тянуть весь граф
# моделей (у media_files есть FK на admin_users и т.п.).
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
    Rental.__table__,
]


class ProductBusyDatesTests(unittest.IsolatedAsyncioTestCase):
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

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _seed(self):
        async with self.SessionLocal() as db:
            city = City(id=uuid4(), name="VN", slug="vn", timezone="Europe/Moscow", is_active=True, sort_order=0)
            category = ProductCategory(id=uuid4(), name="Clean", slug="clean", is_active=True, sort_order=0)
            product = Product(id=uuid4(), category_id=category.id, name="Steam", slug="steam", is_active=True)
            user = User(id=uuid4(), phone="+79990000001", verification_status=VerificationStatus.APPROVED)
            locker = LockerLocation(
                id=uuid4(), city_id=city.id, name="L1", address="A1",
                status=LockerStatus.ONLINE, external_provider="esi", external_locker_id="0980",
            )
            cell = LockerCell(
                id=uuid4(), locker_id=locker.id, label="A1", external_cell_id="A1",
                status=LockerCellStatus.OCCUPIED, supports_return=True,
            )
            unit = InventoryUnit(
                id=uuid4(), product_id=product.id, locker_cell_id=cell.id,
                status=InventoryStatus.RENTED, serial_number="SN-1",
            )
            plan = PricePlan(
                id=uuid4(), product_id=product.id, name="1 день",
                duration_type="day", duration_value=1, base_amount=590, currency="RUB",
                is_active=True, sort_order=0,
            )
            db.add_all([city, category, product, user, locker, cell, unit, plan])
            await db.commit()
            return {
                "city_id": city.id, "product_id": product.id, "user_id": user.id,
                "locker_id": locker.id, "unit_id": unit.id, "plan_id": plan.id,
            }

    async def test_active_rental_blocks_its_dates(self) -> None:
        ids = await self._seed()
        # Аренда: старт сегодня 10:00 МСК, плановый конец через 2 дня.
        start = datetime(2026, 6, 1, 10, 0, tzinfo=MSK)
        end = datetime(2026, 6, 3, 23, 59, tzinfo=MSK)
        async with self.SessionLocal() as db:
            rental = Rental(
                id=uuid4(), user_id=ids["user_id"], inventory_unit_id=ids["unit_id"],
                pickup_locker_id=ids["locker_id"], status=RentalStatus.ACTIVE,
                starts_at=start.astimezone(timezone.utc),
                planned_end_at=end.astimezone(timezone.utc),
            )
            db.add(rental)
            await db.commit()

        async with self.SessionLocal() as db:
            busy = await compute_busy_dates_for_product(db, ids["product_id"])
        self.assertEqual(busy, ["2026-06-01", "2026-06-02", "2026-06-03"])

    async def test_completed_rental_does_not_block(self) -> None:
        ids = await self._seed()
        start = datetime(2026, 6, 1, 10, 0, tzinfo=MSK)
        end = datetime(2026, 6, 3, 23, 59, tzinfo=MSK)
        async with self.SessionLocal() as db:
            rental = Rental(
                id=uuid4(), user_id=ids["user_id"], inventory_unit_id=ids["unit_id"],
                pickup_locker_id=ids["locker_id"], status=RentalStatus.COMPLETED,
                starts_at=start.astimezone(timezone.utc),
                planned_end_at=end.astimezone(timezone.utc),
                completed_at=end.astimezone(timezone.utc),
            )
            db.add(rental)
            await db.commit()

        async with self.SessionLocal() as db:
            busy = await compute_busy_dates_for_product(db, ids["product_id"])
        self.assertEqual(busy, [])

    async def test_confirmed_reservation_with_completed_rental_does_not_block(self) -> None:
        ids = await self._seed()
        start = datetime(2026, 6, 4, 10, 0, tzinfo=MSK)
        end = datetime(2026, 6, 5, 10, 0, tzinfo=MSK)
        async with self.SessionLocal() as db:
            unit = await db.get(InventoryUnit, ids["unit_id"])
            unit.status = InventoryStatus.AVAILABLE

            res = Reservation(
                id=uuid4(), user_id=ids["user_id"], product_id=ids["product_id"],
                inventory_unit_id=ids["unit_id"], locker_id=ids["locker_id"],
                price_plan_id=ids["plan_id"], status=ReservationStatus.CONFIRMED,
                duration_type="day", duration_value=1, quoted_amount=650,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                pickup_at=start.astimezone(timezone.utc),
            )
            rental = Rental(
                id=uuid4(), user_id=ids["user_id"], reservation_id=res.id,
                inventory_unit_id=ids["unit_id"], pickup_locker_id=ids["locker_id"],
                status=RentalStatus.COMPLETED,
                starts_at=start.astimezone(timezone.utc),
                planned_end_at=end.astimezone(timezone.utc),
                actual_end_at=end.astimezone(timezone.utc),
                completed_at=end.astimezone(timezone.utc),
            )
            db.add_all([res, rental])
            await db.commit()

        async with self.SessionLocal() as db:
            busy = await compute_busy_dates_for_product(db, ids["product_id"])
            available_unit = await _get_available_inventory_unit(
                ids["locker_id"],
                ids["product_id"],
                db,
                desired_start=start.astimezone(timezone.utc),
                desired_end=end.astimezone(timezone.utc),
            )

        self.assertEqual(busy, [])
        self.assertIsNotNone(available_unit)
        self.assertEqual(available_unit.id, ids["unit_id"])

    async def test_active_reservation_blocks_dates(self) -> None:
        ids = await self._seed()
        pickup = datetime(2026, 7, 10, 12, 0, tzinfo=MSK)
        async with self.SessionLocal() as db:
            res = Reservation(
                id=uuid4(), user_id=ids["user_id"], product_id=ids["product_id"],
                inventory_unit_id=ids["unit_id"], locker_id=ids["locker_id"],
                price_plan_id=ids["plan_id"], status=ReservationStatus.PAYMENT_AUTHORIZED,
                duration_type="day", duration_value=2, quoted_amount=1180,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                pickup_at=pickup.astimezone(timezone.utc),
            )
            db.add(res)
            await db.commit()

        async with self.SessionLocal() as db:
            busy = await compute_busy_dates_for_product(db, ids["product_id"])
        # 2 дня аренды с 10 июля → 10 и 11 июля.
        self.assertEqual(busy, ["2026-07-10", "2026-07-11"])

    async def test_cancelled_reservation_does_not_block(self) -> None:
        ids = await self._seed()
        pickup = datetime(2026, 7, 10, 12, 0, tzinfo=MSK)
        async with self.SessionLocal() as db:
            res = Reservation(
                id=uuid4(), user_id=ids["user_id"], product_id=ids["product_id"],
                inventory_unit_id=ids["unit_id"], locker_id=ids["locker_id"],
                price_plan_id=ids["plan_id"], status=ReservationStatus.CANCELLED,
                duration_type="day", duration_value=2, quoted_amount=1180,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                pickup_at=pickup.astimezone(timezone.utc),
            )
            db.add(res)
            await db.commit()

        async with self.SessionLocal() as db:
            busy = await compute_busy_dates_for_product(db, ids["product_id"])
        self.assertEqual(busy, [])

    async def test_locker_filter_scopes_busy_dates(self) -> None:
        ids = await self._seed()
        other_locker = uuid4()
        pickup = datetime(2026, 7, 10, 12, 0, tzinfo=MSK)
        async with self.SessionLocal() as db:
            res = Reservation(
                id=uuid4(), user_id=ids["user_id"], product_id=ids["product_id"],
                inventory_unit_id=ids["unit_id"], locker_id=ids["locker_id"],
                price_plan_id=ids["plan_id"], status=ReservationStatus.PAYMENT_AUTHORIZED,
                duration_type="day", duration_value=1, quoted_amount=590,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                pickup_at=pickup.astimezone(timezone.utc),
            )
            db.add(res)
            await db.commit()

        async with self.SessionLocal() as db:
            same = await compute_busy_dates_for_product(db, ids["product_id"], locker_id=ids["locker_id"])
            other = await compute_busy_dates_for_product(db, ids["product_id"], locker_id=other_locker)
        self.assertEqual(same, ["2026-07-10"])
        self.assertEqual(other, [])

    async def test_placed_aggregation_keeps_busy_product_visible(self) -> None:
        ids = await self._seed()  # unit is RENTED (busy)
        async with self.SessionLocal() as db:
            placed_city = await aggregate_placed_in_city(db, ids["city_id"])
            placed_global = await aggregate_placed_globally(db)
        # Товар занят (RENTED), но всё равно числится размещённым → виден.
        self.assertIn(ids["product_id"], placed_city)
        self.assertIn(ids["product_id"], placed_global)


    async def test_awaiting_confirmation_is_visible_but_not_bookable(self) -> None:
        ids = await self._seed()
        async with self.SessionLocal() as db:
            unit = await db.get(InventoryUnit, ids["unit_id"])
            unit.status = InventoryStatus.AWAITING_CONFIRMATION
            await db.commit()

        async with self.SessionLocal() as db:
            placed_city = await aggregate_placed_in_city(db, ids["city_id"])
            available_unit = await _get_available_inventory_unit(
                ids["locker_id"],
                ids["product_id"],
                db,
            )

        self.assertIn(ids["product_id"], placed_city)
        self.assertIsNone(available_unit)


if __name__ == "__main__":
    unittest.main()
