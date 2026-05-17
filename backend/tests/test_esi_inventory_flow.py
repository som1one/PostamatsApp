import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.core.settings import settings
from backend.models.city import City
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    RentalStatus,
    ReturnRequestStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.admin_user import AdminUser
from backend.models.inventory_movement import InventoryMovement
from backend.models.esi_event_log import EsiEventLog
from backend.models.media_file import MediaFile
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.models.return_request import ReturnRequest
from backend.models.user import User
from backend.utils.esi_reconcile import reconcile_esi_and_returns
from backend.utils.esi_webhook_handler import process_esi_webhook_payload
from backend.utils.rental_overdue import mark_overdue_rentals
from backend.utils.rental_return_flow import start_rental_return

TEST_DB_URL = "sqlite+aiosqlite:///test_esi_flow.sqlite"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)

TEST_TABLES = [
    City.__table__,
    ProductCategory.__table__,
    Product.__table__,
    User.__table__,
    AdminUser.__table__,
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
    EsiEventLog.__table__,
]


class EsiInventoryFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_stub = settings.ESI_DEV_STUB
        self.original_base_url = settings.ESI_BASE_URL
        settings.ESI_DEV_STUB = True
        settings.ESI_BASE_URL = None
        self.reconcile_session_patcher = patch("backend.utils.esi_reconcile.SessionLocal", TestSessionLocal)
        self.overdue_session_patcher = patch("backend.utils.rental_overdue.SessionLocal", TestSessionLocal)
        self.reconcile_session_patcher.start()
        self.overdue_session_patcher.start()
        async with test_engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=TEST_TABLES))

    async def asyncTearDown(self):
        settings.ESI_DEV_STUB = self.original_stub
        settings.ESI_BASE_URL = self.original_base_url
        self.reconcile_session_patcher.stop()
        self.overdue_session_patcher.stop()
        async with test_engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: Base.metadata.drop_all(sync_conn, tables=list(reversed(TEST_TABLES))))
        await test_engine.dispose()

    async def _seed_rental_graph(
        self,
        *,
        rental_status: RentalStatus,
        unit_status: InventoryStatus,
        cell_status: LockerCellStatus,
        unit_in_cell: bool = True,
    ):
        async with TestSessionLocal() as db:
            city = City(id=uuid4(), name="Minsk", slug="minsk", timezone="Europe/Minsk", is_active=True, sort_order=0)
            category = ProductCategory(id=uuid4(), name="Consoles", slug="consoles", is_active=True, sort_order=0)
            product = Product(id=uuid4(), category_id=category.id, name="PS5", slug="ps5", is_active=True)
            user = User(id=uuid4(), phone="+79990000001", verification_status=VerificationStatus.APPROVED)
            locker = LockerLocation(
                id=uuid4(),
                city_id=city.id,
                name="Locker A",
                address="Center, 1",
                status=LockerStatus.ONLINE,
                external_provider="esi",
                external_locker_id="LOCKER-001",
            )
            cell = LockerCell(
                id=uuid4(),
                locker_id=locker.id,
                label="A1",
                external_cell_id="A1",
                status=cell_status,
                supports_return=True,
            )
            unit = InventoryUnit(
                id=uuid4(),
                product_id=product.id,
                locker_cell_id=cell.id if unit_in_cell else None,
                status=unit_status,
                serial_number="SN-001",
            )
            rental = Rental(
                id=uuid4(),
                user_id=user.id,
                inventory_unit_id=unit.id,
                pickup_locker_id=locker.id,
                pickup_pin="1234",
                status=rental_status,
                planned_end_at=datetime.now(timezone.utc) + timedelta(days=1),
            )

            db.add_all([city, category, product, user, locker, cell, unit, rental])
            await db.commit()
            return {
                "city_id": city.id,
                "category_id": category.id,
                "product_id": product.id,
                "user_id": user.id,
                "locker_id": locker.id,
                "cell_id": cell.id,
                "unit_id": unit.id,
                "rental_id": rental.id,
            }

    async def test_pickup_complete_webhook_clears_cell_and_marks_unit_rented(self):
        ids = await self._seed_rental_graph(
            rental_status=RentalStatus.PICKUP_READY,
            unit_status=InventoryStatus.RESERVED,
            cell_status=LockerCellStatus.RESERVED,
            unit_in_cell=True,
        )

        async with TestSessionLocal() as db:
            await process_esi_webhook_payload(
                db,
                payload={
                    "eventType": "pickup_complete",
                    "eventId": "evt-pickup-1",
                    "rentalId": str(ids["rental_id"]),
                    "lockerId": "LOCKER-001",
                    "cellId": "A1",
                },
            )

            rental = await db.get(Rental, ids["rental_id"])
            unit = await db.get(InventoryUnit, ids["unit_id"])
            cell = await db.get(LockerCell, ids["cell_id"])

            self.assertEqual(rental.status, RentalStatus.ACTIVE)
            self.assertEqual(unit.status, InventoryStatus.RENTED)
            self.assertIsNone(unit.locker_cell_id)
            self.assertEqual(cell.status, LockerCellStatus.VACANT)

    async def test_return_request_reuses_active_request_and_close_completes_return(self):
        ids = await self._seed_rental_graph(
            rental_status=RentalStatus.ACTIVE,
            unit_status=InventoryStatus.RENTED,
            cell_status=LockerCellStatus.VACANT,
            unit_in_cell=False,
        )

        async with TestSessionLocal() as db:
            rental = await db.get(Rental, ids["rental_id"])
            first = await start_rental_return(db, rental=rental, return_locker_id=ids["locker_id"])
            second = await start_rental_return(db, rental=rental, return_locker_id=ids["locker_id"])
            self.assertEqual(first["id"], second["id"])

            await process_esi_webhook_payload(
                db,
                payload={
                    "eventType": "return_cell_closed",
                    "eventId": "evt-return-1",
                    "lockerId": "LOCKER-001",
                    "cellId": "A1",
                },
            )

            rental = await db.get(Rental, ids["rental_id"])
            unit = await db.get(InventoryUnit, ids["unit_id"])
            cell = await db.get(LockerCell, ids["cell_id"])
            request = await db.get(ReturnRequest, UUID(first["id"]))

            self.assertEqual(rental.status, RentalStatus.COMPLETED)
            self.assertEqual(unit.status, InventoryStatus.AVAILABLE)
            self.assertEqual(unit.locker_cell_id, ids["cell_id"])
            self.assertEqual(cell.status, LockerCellStatus.OCCUPIED)
            self.assertEqual(request.status, ReturnRequestStatus.COMPLETED)

    async def test_reconcile_fails_stale_return_requests(self):
        ids = await self._seed_rental_graph(
            rental_status=RentalStatus.RETURN_IN_PROGRESS,
            unit_status=InventoryStatus.RETURN_PENDING,
            cell_status=LockerCellStatus.OPENED,
            unit_in_cell=False,
        )

        async with TestSessionLocal() as db:
            request = ReturnRequest(
                rental_id=ids["rental_id"],
                locker_id=ids["locker_id"],
                cell_id=ids["cell_id"],
                pin="9999",
                status=ReturnRequestStatus.LOCKER_OPENED,
                requested_at=datetime.now(timezone.utc) - timedelta(minutes=40),
                deadline_at=datetime.now(timezone.utc) - timedelta(minutes=10),
                opened_at=datetime.now(timezone.utc) - timedelta(minutes=40),
            )
            db.add(request)
            await db.commit()
            request_id = request.id

            await reconcile_esi_and_returns()
        async with TestSessionLocal() as db:
            rental = await db.get(Rental, ids["rental_id"])
            unit = await db.get(InventoryUnit, ids["unit_id"])
            cell = await db.get(LockerCell, ids["cell_id"])
            request = await db.get(ReturnRequest, request_id)

            self.assertEqual(request.status, ReturnRequestStatus.FAILED)
            self.assertEqual(rental.status, RentalStatus.INCIDENT)
            self.assertEqual(unit.status, InventoryStatus.RETURN_PENDING)
            self.assertEqual(cell.status, LockerCellStatus.VACANT)

    async def test_overdue_scheduler_marks_active_rental_overdue(self):
        ids = await self._seed_rental_graph(
            rental_status=RentalStatus.ACTIVE,
            unit_status=InventoryStatus.RENTED,
            cell_status=LockerCellStatus.VACANT,
            unit_in_cell=False,
        )

        async with TestSessionLocal() as db:
            rental = await db.get(Rental, ids["rental_id"])
            rental.planned_end_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            await db.commit()

            await mark_overdue_rentals()
        async with TestSessionLocal() as db:
            rental = await db.get(Rental, ids["rental_id"])
            self.assertEqual(rental.status, RentalStatus.OVERDUE)


if __name__ == "__main__":
    unittest.main()
