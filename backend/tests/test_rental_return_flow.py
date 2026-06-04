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
            self.assertEqual(request.status, ReturnRequestStatus.LOCKER_OPENED)
            self.assertEqual(request.cell_id, cell.id)
            self.assertEqual(rental.status, RentalStatus.RETURN_IN_PROGRESS)
            self.assertEqual(unit.status, InventoryStatus.RETURN_PENDING)
            self.assertIsNone(unit.locker_cell_id)
            self.assertEqual(cell.status, LockerCellStatus.OPENED)


if __name__ == "__main__":
    unittest.main()
