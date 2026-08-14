"""Тесты авто-подтверждения выдачи (backend/utils/rental_auto_pickup.py).

Момент открытия ячейки в таблице rentals не хранится — планировщик берёт
его из события перехода в PICKUP_OPENED. Проверяем и сам таймаут, и то,
что «свежие» открытия шедулер не трогает.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

# DSN и стабы перекрываем ДО импорта приложения (как в остальных тестах).
TEST_DB_PATH = os.path.abspath(
    f"./backend/tests/test_auto_pickup_{uuid4().hex}.sqlite"
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
    RentalEventSource,
    RentalStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.rental import Rental  # noqa: E402
from backend.models.rental_event import RentalEvent  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.rental_auto_pickup import (  # noqa: E402
    AUTO_PICKUP_TIMEOUT_MINUTES,
    auto_confirm_opened_pickups,
)


class RentalAutoPickupTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_rental(
        self,
        *,
        status: RentalStatus,
        opened_ago: list[timedelta],
    ) -> Rental:
        """Аренда с ячейкой и событиями открытия в заданные моменты."""

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
            rental = Rental(
                id=uuid4(),
                user_id=self.user_id,
                inventory_unit_id=unit.id,
                pickup_locker_id=locker.id,
                status=status,
                planned_end_at=now + timedelta(days=1),
            )
            db.add_all([locker, cell, unit, rental])
            for delta in opened_ago:
                opened_at = now - delta
                db.add(
                    RentalEvent(
                        id=uuid4(),
                        rental_id=rental.id,
                        event_type="pickup_cell_opened",
                        from_status=RentalStatus.PICKUP_READY,
                        to_status=RentalStatus.PICKUP_OPENED,
                        source=RentalEventSource.USER,
                        created_at=opened_at,
                        updated_at=opened_at,
                    )
                )
            await db.commit()
            self.cell_id = cell.id
            self.unit_id = unit.id
            return rental

    async def _reload(self, rental_id):
        async with SessionLocal() as db:
            rental = await db.get(Rental, rental_id)
            unit = await db.get(InventoryUnit, self.unit_id)
            cell = await db.get(LockerCell, self.cell_id)
            events = list(
                (
                    await db.scalars(
                        select(RentalEvent).where(
                            RentalEvent.rental_id == rental_id,
                            RentalEvent.event_type == "auto_pickup_confirmed",
                        )
                    )
                ).all()
            )
            return rental, unit, cell, events

    async def test_stale_open_cell_is_auto_confirmed(self):
        stale = timedelta(minutes=AUTO_PICKUP_TIMEOUT_MINUTES + 5)
        rental = await self._seed_rental(
            status=RentalStatus.PICKUP_OPENED, opened_ago=[stale]
        )

        await auto_confirm_opened_pickups()

        updated, unit, cell, events = await self._reload(rental.id)
        self.assertEqual(updated.status, RentalStatus.ACTIVE)
        self.assertIsNotNone(updated.starts_at)
        self.assertEqual(unit.status, InventoryStatus.RENTED)
        self.assertIsNone(unit.locker_cell_id)
        self.assertEqual(cell.status, LockerCellStatus.VACANT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload_json["trigger"], "auto_pickup_timeout")
        # Момент открытия попадает в событие — по нему видно, от чего считали.
        self.assertIsNotNone(events[0].payload_json["cellOpenedAt"])

    async def test_fresh_open_cell_is_left_alone(self):
        rental = await self._seed_rental(
            status=RentalStatus.PICKUP_OPENED,
            opened_ago=[timedelta(minutes=AUTO_PICKUP_TIMEOUT_MINUTES - 5)],
        )

        await auto_confirm_opened_pickups()

        updated, unit, cell, events = await self._reload(rental.id)
        self.assertEqual(updated.status, RentalStatus.PICKUP_OPENED)
        self.assertEqual(unit.status, InventoryStatus.RESERVED)
        self.assertEqual(cell.status, LockerCellStatus.OCCUPIED)
        self.assertEqual(events, [])

    async def test_counts_from_the_latest_open(self):
        """Открыли час назад и ещё раз только что — таймаут идёт от последнего."""

        rental = await self._seed_rental(
            status=RentalStatus.PICKUP_OPENED,
            opened_ago=[timedelta(hours=1), timedelta(minutes=1)],
        )

        await auto_confirm_opened_pickups()

        updated, _unit, _cell, events = await self._reload(rental.id)
        self.assertEqual(updated.status, RentalStatus.PICKUP_OPENED)
        self.assertEqual(events, [])

    async def test_other_statuses_are_untouched(self):
        """Ячейку не открывали: событий нет, аренда ждёт клиента."""

        rental = await self._seed_rental(
            status=RentalStatus.PICKUP_READY, opened_ago=[]
        )

        await auto_confirm_opened_pickups()

        updated, unit, _cell, events = await self._reload(rental.id)
        self.assertEqual(updated.status, RentalStatus.PICKUP_READY)
        self.assertEqual(unit.status, InventoryStatus.RESERVED)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
