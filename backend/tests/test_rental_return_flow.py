from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("UPLOAD_DEV_STUB", "true")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.core.settings import settings
from backend.models.admin_account import AdminAccount
from backend.models.city import City
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    RentalStatus,
    ReturnRequestStatus,
    VerificationStatus,
)
from backend.models.inventory_movement import InventoryMovement
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
from backend.models.return_request import ReturnRequest
from backend.models.user import User
from backend.utils.rental_return_flow import start_rental_return

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

TEST_TABLES = [
    City.__table__,
    ProductCategory.__table__,
    Product.__table__,
    User.__table__,
    AdminAccount.__table__,
    MediaFile.__table__,
    LockerLocation.__table__,
    LockerCell.__table__,
    InventoryUnit.__table__,
    PricePlan.__table__,
    Reservation.__table__,
    Rental.__table__,
    RentalEvent.__table__,
    ReturnRequest.__table__,
    InventoryMovement.__table__,
]


class RentalReturnFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_esi_stub = settings.ESI_DEV_STUB
        settings.ESI_DEV_STUB = True
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
        settings.ESI_DEV_STUB = self.original_esi_stub
        await self.engine.dispose()

    async def test_reuses_legacy_pickup_cell_when_no_free_return_cells(self) -> None:
        async with self.SessionLocal() as db:
            city = City(
                id=uuid4(),
                name="Veliky Novgorod",
                slug="vn",
                timezone="Europe/Moscow",
                is_active=True,
                sort_order=0,
            )
            category = ProductCategory(
                id=uuid4(), name="Audio", slug="audio", is_active=True, sort_order=0
            )
            product = Product(
                id=uuid4(),
                category_id=category.id,
                name="Karaoke",
                slug="karaoke",
                is_active=True,
            )
            user = User(
                id=uuid4(),
                phone="+79990000001",
                verification_status=VerificationStatus.APPROVED,
            )
            locker = LockerLocation(
                id=uuid4(),
                city_id=city.id,
                name="Veliky Novgorod Center",
                address="Bolshaya Sankt-Peterburgskaya st., 39",
                status=LockerStatus.ONLINE,
                external_provider="esi",
                external_locker_id="VN-1",
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
                product_id=product.id,
                locker_cell_id=None,
                status=InventoryStatus.RENTED,
                serial_number="SN-KARAOKE-1",
            )
            rental = Rental(
                id=uuid4(),
                user_id=user.id,
                inventory_unit_id=unit.id,
                pickup_locker_id=locker.id,
                status=RentalStatus.ACTIVE,
                starts_at=datetime.now(timezone.utc) - timedelta(days=1),
                planned_end_at=datetime.now(timezone.utc) + timedelta(hours=10),
            )
            movement = InventoryMovement(
                inventory_unit_id=unit.id,
                from_locker_id=locker.id,
                to_locker_id=None,
                from_cell_id=cell.id,
                to_cell_id=None,
                from_status=InventoryStatus.RESERVED,
                to_status=InventoryStatus.RENTED,
                reason="pickup_confirmed_by_user",
            )
            db.add_all([city, category, product, user, locker, cell, unit, rental, movement])
            await db.commit()

            result = await start_rental_return(
                db, rental=rental, return_locker_id=locker.id
            )

            request = await db.get(ReturnRequest, UUID(result["id"]))
            self.assertEqual(result["cellId"], str(cell.id))
            # PIN-флоу: заявка создаётся в CREATED, ячейка резервируется
            # с PIN-кодом — дверь не открывается до ввода PIN клиентом.
            self.assertEqual(request.status, ReturnRequestStatus.CREATED)
            self.assertEqual(request.cell_id, cell.id)
            self.assertEqual(rental.status, RentalStatus.RETURN_IN_PROGRESS)
            self.assertEqual(unit.status, InventoryStatus.RETURN_PENDING)
            self.assertIsNone(unit.locker_cell_id)
            self.assertEqual(cell.status, LockerCellStatus.RESERVED)


class SameCellReturnTests(unittest.IsolatedAsyncioTestCase):
    """Возврат должен идти в «родную» ячейку — ту, откуда товар забрали."""

    async def asyncSetUp(self) -> None:
        self.original_esi_stub = settings.ESI_DEV_STUB
        settings.ESI_DEV_STUB = True
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
        settings.ESI_DEV_STUB = self.original_esi_stub
        await self.engine.dispose()

    async def _seed(self, db: AsyncSession) -> dict:
        """Базовый каталог: аренда unit-а, выданного из ячейки B2.

        Ячейки: A1 (VACANT, первая по алфавиту — её выбрал бы старый
        алгоритм) и B2 («родная», статус задаёт тест).
        """
        city = City(
            id=uuid4(),
            name="Veliky Novgorod",
            slug="vn",
            timezone="Europe/Moscow",
            is_active=True,
            sort_order=0,
        )
        category = ProductCategory(
            id=uuid4(), name="Audio", slug="audio", is_active=True, sort_order=0
        )
        product = Product(
            id=uuid4(),
            category_id=category.id,
            name="Karaoke",
            slug="karaoke",
            is_active=True,
        )
        user = User(
            id=uuid4(),
            phone="+79990000002",
            verification_status=VerificationStatus.APPROVED,
        )
        locker = LockerLocation(
            id=uuid4(),
            city_id=city.id,
            name="VN Center",
            address="Bolshaya st., 39",
            status=LockerStatus.ONLINE,
            external_provider="esi",
            external_locker_id="VN-2",
        )
        vacant_cell = LockerCell(
            id=uuid4(),
            locker_id=locker.id,
            label="A1",
            external_cell_id="A1",
            status=LockerCellStatus.VACANT,
            supports_return=True,
        )
        home_cell = LockerCell(
            id=uuid4(),
            locker_id=locker.id,
            label="B2",
            external_cell_id="B2",
            status=LockerCellStatus.VACANT,
            supports_return=True,
        )
        unit = InventoryUnit(
            id=uuid4(),
            product_id=product.id,
            locker_cell_id=None,
            status=InventoryStatus.RENTED,
            serial_number="SN-KARAOKE-2",
        )
        rental = Rental(
            id=uuid4(),
            user_id=user.id,
            inventory_unit_id=unit.id,
            pickup_locker_id=locker.id,
            status=RentalStatus.ACTIVE,
            starts_at=datetime.now(timezone.utc) - timedelta(days=1),
            planned_end_at=datetime.now(timezone.utc) + timedelta(hours=10),
        )
        movement = InventoryMovement(
            inventory_unit_id=unit.id,
            from_locker_id=locker.id,
            to_locker_id=None,
            from_cell_id=home_cell.id,
            to_cell_id=None,
            from_status=InventoryStatus.RESERVED,
            to_status=InventoryStatus.RENTED,
            reason="pickup_confirmed_by_user",
        )
        db.add_all(
            [
                city,
                category,
                product,
                user,
                locker,
                vacant_cell,
                home_cell,
                unit,
                rental,
                movement,
            ]
        )
        await db.commit()
        return {
            "locker": locker,
            "vacant_cell": vacant_cell,
            "home_cell": home_cell,
            "unit": unit,
            "rental": rental,
            "product": product,
            "user": user,
        }

    async def test_return_prefers_home_cell_over_first_vacant(self) -> None:
        """Родная B2 свободна → возврат в неё, а не в A1 (первую по алфавиту)."""
        async with self.SessionLocal() as db:
            seeded = await self._seed(db)

            result = await start_rental_return(
                db, rental=seeded["rental"], return_locker_id=seeded["locker"].id
            )

            self.assertEqual(result["cellId"], str(seeded["home_cell"].id))
            request = await db.get(ReturnRequest, UUID(result["id"]))
            self.assertEqual(request.cell_id, seeded["home_cell"].id)
            self.assertEqual(seeded["home_cell"].status, LockerCellStatus.RESERVED)
            # Свободная A1 не тронута.
            self.assertEqual(seeded["vacant_cell"].status, LockerCellStatus.VACANT)

    async def test_home_cell_taken_by_other_unit_falls_back_to_vacant(self) -> None:
        """В родной B2 уже лежит другой товар → возврат в первую свободную A1."""
        async with self.SessionLocal() as db:
            seeded = await self._seed(db)
            other_unit = InventoryUnit(
                id=uuid4(),
                product_id=seeded["product"].id,
                locker_cell_id=seeded["home_cell"].id,
                status=InventoryStatus.AVAILABLE,
                serial_number="SN-OTHER-1",
            )
            seeded["home_cell"].status = LockerCellStatus.OCCUPIED
            db.add(other_unit)
            await db.commit()

            result = await start_rental_return(
                db, rental=seeded["rental"], return_locker_id=seeded["locker"].id
            )

            self.assertEqual(result["cellId"], str(seeded["vacant_cell"].id))

    async def test_home_cell_held_by_foreign_return_falls_back(self) -> None:
        """Родную B2 держит чужой активный возврат → не перезаписываем его PIN."""
        async with self.SessionLocal() as db:
            seeded = await self._seed(db)
            other_unit = InventoryUnit(
                id=uuid4(),
                product_id=seeded["product"].id,
                locker_cell_id=None,
                status=InventoryStatus.RETURN_PENDING,
                serial_number="SN-OTHER-2",
            )
            other_rental = Rental(
                id=uuid4(),
                user_id=seeded["user"].id,
                inventory_unit_id=other_unit.id,
                pickup_locker_id=seeded["locker"].id,
                status=RentalStatus.RETURN_IN_PROGRESS,
                starts_at=datetime.now(timezone.utc) - timedelta(days=2),
                planned_end_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            foreign_request = ReturnRequest(
                rental_id=other_rental.id,
                locker_id=seeded["locker"].id,
                cell_id=seeded["home_cell"].id,
                pin="1234",
                status=ReturnRequestStatus.CREATED,
                requested_at=datetime.now(timezone.utc),
                deadline_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            # Ячейка нарочно остаётся VACANT (рассинхрон после reconcile):
            # отфильтровать её обязана именно проверка чужой активной заявки,
            # а не статус ячейки.
            db.add_all([other_unit, other_rental, foreign_request])
            await db.commit()

            result = await start_rental_return(
                db, rental=seeded["rental"], return_locker_id=seeded["locker"].id
            )

            self.assertEqual(result["cellId"], str(seeded["vacant_cell"].id))
            # Чужая заявка не тронута.
            self.assertEqual(foreign_request.cell_id, seeded["home_cell"].id)
            self.assertEqual(foreign_request.pin, "1234")

    async def test_foreign_return_cell_never_selected_even_when_first_by_label(self) -> None:
        """Ячейка чужого возврата первая по алфавиту → общий подбор тоже обязан
        её пропустить, а не только «родной» путь."""
        async with self.SessionLocal() as db:
            seeded = await self._seed(db)
            # Родная ячейка сортируется ПЕРВОЙ: без фильтра в общем подборе
            # fallback выбрал бы её и перезаписал чужой PIN.
            seeded["home_cell"].label = "A0"
            seeded["home_cell"].external_cell_id = "A0"
            other_unit = InventoryUnit(
                id=uuid4(),
                product_id=seeded["product"].id,
                locker_cell_id=None,
                status=InventoryStatus.RETURN_PENDING,
                serial_number="SN-OTHER-3",
            )
            other_rental = Rental(
                id=uuid4(),
                user_id=seeded["user"].id,
                inventory_unit_id=other_unit.id,
                pickup_locker_id=seeded["locker"].id,
                status=RentalStatus.RETURN_IN_PROGRESS,
                starts_at=datetime.now(timezone.utc) - timedelta(days=2),
                planned_end_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            foreign_request = ReturnRequest(
                rental_id=other_rental.id,
                locker_id=seeded["locker"].id,
                cell_id=seeded["home_cell"].id,
                pin="4321",
                status=ReturnRequestStatus.CREATED,
                requested_at=datetime.now(timezone.utc),
                deadline_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add_all([other_unit, other_rental, foreign_request])
            await db.commit()

            result = await start_rental_return(
                db, rental=seeded["rental"], return_locker_id=seeded["locker"].id
            )

            self.assertEqual(result["cellId"], str(seeded["vacant_cell"].id))
            self.assertEqual(foreign_request.pin, "4321")

    async def test_home_cell_reserved_stale_after_pickup_is_chosen(self) -> None:
        """Прод-кейс: возврат через минуту после забора — reconcile успел
        перезаписать родной ячейке VACANT на RESERVED по снапшоту ESI.
        Ячейка физически пуста (наш товар на руках) → возврат в неё же."""
        async with self.SessionLocal() as db:
            seeded = await self._seed(db)
            seeded["home_cell"].status = LockerCellStatus.RESERVED
            await db.commit()

            result = await start_rental_return(
                db, rental=seeded["rental"], return_locker_id=seeded["locker"].id
            )

            self.assertEqual(result["cellId"], str(seeded["home_cell"].id))

    async def test_home_cell_opened_stale_after_pickup_is_chosen(self) -> None:
        """То же, но reconcile зафиксировал OPENED (дверь была открыта в момент
        снапшота — клиент как раз забирал товар)."""
        async with self.SessionLocal() as db:
            seeded = await self._seed(db)
            seeded["home_cell"].status = LockerCellStatus.OPENED
            await db.commit()

            result = await start_rental_return(
                db, rental=seeded["rental"], return_locker_id=seeded["locker"].id
            )

            self.assertEqual(result["cellId"], str(seeded["home_cell"].id))

    async def test_home_cell_reserved_after_failed_foreign_return_falls_back(self) -> None:
        """RESERVED + проваленный чужой возврат после нашей выдачи: товар могли
        физически положить (потерянный вебхук) — ячейку не трогаем."""
        async with self.SessionLocal() as db:
            seeded = await self._seed(db)
            seeded["home_cell"].status = LockerCellStatus.RESERVED
            other_unit = InventoryUnit(
                id=uuid4(),
                product_id=seeded["product"].id,
                locker_cell_id=None,
                status=InventoryStatus.RETURN_PENDING,
                serial_number="SN-OTHER-5",
            )
            other_rental = Rental(
                id=uuid4(),
                user_id=seeded["user"].id,
                inventory_unit_id=other_unit.id,
                pickup_locker_id=seeded["locker"].id,
                status=RentalStatus.INCIDENT,
                starts_at=datetime.now(timezone.utc) - timedelta(days=3),
                planned_end_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
            failed_request = ReturnRequest(
                rental_id=other_rental.id,
                locker_id=seeded["locker"].id,
                cell_id=seeded["home_cell"].id,
                pin="9999",
                status=ReturnRequestStatus.FAILED,
                requested_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                deadline_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add_all([other_unit, other_rental, failed_request])
            await db.commit()

            result = await start_rental_return(
                db, rental=seeded["rental"], return_locker_id=seeded["locker"].id
            )

            self.assertEqual(result["cellId"], str(seeded["vacant_cell"].id))

    async def test_home_cell_occupied_after_failed_foreign_return_falls_back(self) -> None:
        """После нашей выдачи в родную ячейку оформляли (проваленный) возврат —
        товар мог быть физически внутри, ячейку не трогаем."""
        async with self.SessionLocal() as db:
            seeded = await self._seed(db)
            seeded["home_cell"].status = LockerCellStatus.OCCUPIED
            other_unit = InventoryUnit(
                id=uuid4(),
                product_id=seeded["product"].id,
                # Клиент положил товар, но вебхук закрытия потерялся: заявка
                # провалена по дедлайну, locker_cell_id так и не проставлен.
                locker_cell_id=None,
                status=InventoryStatus.RETURN_PENDING,
                serial_number="SN-OTHER-4",
            )
            other_rental = Rental(
                id=uuid4(),
                user_id=seeded["user"].id,
                inventory_unit_id=other_unit.id,
                pickup_locker_id=seeded["locker"].id,
                status=RentalStatus.INCIDENT,
                starts_at=datetime.now(timezone.utc) - timedelta(days=3),
                planned_end_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
            failed_request = ReturnRequest(
                rental_id=other_rental.id,
                locker_id=seeded["locker"].id,
                cell_id=seeded["home_cell"].id,
                pin="7777",
                status=ReturnRequestStatus.FAILED,
                # Заведомо позже pickup-движения нашего товара.
                requested_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                deadline_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add_all([other_unit, other_rental, failed_request])
            await db.commit()

            result = await start_rental_return(
                db, rental=seeded["rental"], return_locker_id=seeded["locker"].id
            )

            self.assertEqual(result["cellId"], str(seeded["vacant_cell"].id))


if __name__ == "__main__":
    unittest.main()
