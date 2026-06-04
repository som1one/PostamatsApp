import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.core.settings import settings
from backend.models.admin_account import AdminAccount
from backend.models.admin_audit_event import AdminAuditEvent
from backend.models.admin_user import AdminUser
from backend.models.city import City
from backend.models.enums import AdminRole, InventoryStatus, LockerCellStatus, LockerStatus
from backend.models.inventory_movement import InventoryMovement
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.routers.admin import inventory as inventory_router
from backend.schemas.admin_panel_schemas import (
    AdminConfirmInventoryReadyPayload,
    AdminPlaceProductInCellPayload,
    AdminTakeForServicePayload,
)


TEST_DB_URL = "sqlite+aiosqlite:///test_admin_inventory_placement.sqlite"
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
    AdminAccount.__table__,
    AdminUser.__table__,
    AdminAuditEvent.__table__,
    LockerLocation.__table__,
    LockerCell.__table__,
    InventoryUnit.__table__,
    InventoryMovement.__table__,
]


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"user-agent", b"pytest")],
        "path": "/api/admin/inventory",
        "client": ("127.0.0.1", 0),
    }
    return Request(scope)


class AdminInventoryPlacementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_stub = settings.ESI_DEV_STUB
        self.original_base_url = settings.ESI_BASE_URL
        settings.ESI_DEV_STUB = True
        settings.ESI_BASE_URL = None

        async with test_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=TEST_TABLES)
            )

        # Build a baseline admin + city + product + locker + cell.
        async with TestSessionLocal() as db:
            admin = AdminAccount(
                id=uuid4(),
                name="Test Admin",
                login="test-admin",
                role=AdminRole.SUPER_ADMIN,
                password_hash="x",
            )
            city = City(
                id=uuid4(),
                name="Minsk",
                slug="minsk",
                timezone="Europe/Minsk",
                is_active=True,
                sort_order=0,
            )
            category = ProductCategory(
                id=uuid4(),
                name="Consoles",
                slug="consoles",
                is_active=True,
                sort_order=0,
            )
            product = Product(
                id=uuid4(),
                category_id=category.id,
                name="PS5",
                slug="ps5",
                is_active=True,
            )
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
                status=LockerCellStatus.VACANT,
                supports_return=True,
            )
            db.add_all([admin, city, category, product, locker, cell])
            await db.commit()

            self.admin_id = admin.id
            self.city_id = city.id
            self.product_id = product.id
            self.locker_id = locker.id
            self.cell_id = cell.id

        async def fake_get_current_admin(request, db):
            account = await db.get(AdminAccount, self.admin_id)
            return account, None

        self.auth_patcher = patch(
            "backend.routers.admin.inventory.get_current_admin",
            new=fake_get_current_admin,
        )
        self.auth_patcher.start()

    async def asyncTearDown(self):
        self.auth_patcher.stop()
        settings.ESI_DEV_STUB = self.original_stub
        settings.ESI_BASE_URL = self.original_base_url
        async with test_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.drop_all(
                    sync_conn, tables=list(reversed(TEST_TABLES))
                )
            )
        await test_engine.dispose()

    async def test_place_creates_unit_when_no_free_unit_exists(self):
        async with TestSessionLocal() as db:
            payload = AdminPlaceProductInCellPayload(productId=self.product_id)
            response = await inventory_router.place_product_in_cell(
                _make_request(), self.cell_id, payload, db
            )
            data = response["data"]
            self.assertTrue(data["createdNewUnit"])
            self.assertIsNotNone(data["cell"]["currentUnit"])
            self.assertEqual(data["cell"]["status"], LockerCellStatus.OCCUPIED.value)

        async with TestSessionLocal() as db:
            cell = await db.get(LockerCell, self.cell_id)
            self.assertEqual(cell.status, LockerCellStatus.OCCUPIED)
            unit = (
                await db.execute(
                    select(InventoryUnit).where(InventoryUnit.locker_cell_id == self.cell_id)
                )
            ).scalar_one()
            self.assertEqual(unit.product_id, self.product_id)
            self.assertEqual(unit.status, InventoryStatus.AVAILABLE)

            movements = (
                await db.scalars(
                    select(InventoryMovement).where(
                        InventoryMovement.inventory_unit_id == unit.id
                    )
                )
            ).all()
            self.assertEqual(len(movements), 1)
            self.assertEqual(movements[0].reason, "admin_place_in_cell")
            self.assertEqual(movements[0].to_cell_id, self.cell_id)
            self.assertEqual(movements[0].performed_by_admin_id, self.admin_id)

            audits = (
                await db.scalars(
                    select(AdminAuditEvent).where(AdminAuditEvent.action == "inventory.place")
                )
            ).all()
            self.assertEqual(len(audits), 1)

    async def test_place_reuses_existing_free_unit(self):
        async with TestSessionLocal() as db:
            existing = InventoryUnit(
                id=uuid4(),
                product_id=self.product_id,
                status=InventoryStatus.AVAILABLE,
                locker_cell_id=None,
                serial_number="SN-EXISTING",
            )
            db.add(existing)
            await db.commit()
            existing_id = existing.id

        async with TestSessionLocal() as db:
            payload = AdminPlaceProductInCellPayload(productId=self.product_id)
            response = await inventory_router.place_product_in_cell(
                _make_request(), self.cell_id, payload, db
            )
            self.assertFalse(response["data"]["createdNewUnit"])
            self.assertEqual(response["data"]["cell"]["currentUnit"]["id"], str(existing_id))

        async with TestSessionLocal() as db:
            units = (
                await db.scalars(
                    select(InventoryUnit).where(InventoryUnit.product_id == self.product_id)
                )
            ).all()
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0].id, existing_id)
            self.assertEqual(units[0].locker_cell_id, self.cell_id)

    async def test_place_rejects_already_occupied_cell(self):
        async with TestSessionLocal() as db:
            cell = await db.get(LockerCell, self.cell_id)
            cell.status = LockerCellStatus.OCCUPIED
            await db.commit()

        async with TestSessionLocal() as db:
            payload = AdminPlaceProductInCellPayload(productId=self.product_id)
            with self.assertRaises(Exception) as ctx:
                await inventory_router.place_product_in_cell(
                    _make_request(), self.cell_id, payload, db
                )
            self.assertEqual(getattr(ctx.exception, "status_code", None), 409)

    async def test_take_for_service_marks_maintenance_and_frees_cell(self):
        async with TestSessionLocal() as db:
            payload = AdminPlaceProductInCellPayload(productId=self.product_id)
            await inventory_router.place_product_in_cell(
                _make_request(), self.cell_id, payload, db
            )
        async with TestSessionLocal() as db:
            unit_before = (
                await db.execute(
                    select(InventoryUnit).where(InventoryUnit.locker_cell_id == self.cell_id)
                )
            ).scalar_one()
            unit_id = unit_before.id

        async with TestSessionLocal() as db:
            response = await inventory_router.take_cell_for_service(
                _make_request(),
                self.cell_id,
                AdminTakeForServicePayload(reason="починить корпус"),
                db,
            )
            self.assertEqual(response["data"]["cell"]["status"], LockerCellStatus.VACANT.value)
            self.assertIsNone(response["data"]["cell"]["currentUnit"])

        async with TestSessionLocal() as db:
            cell = await db.get(LockerCell, self.cell_id)
            self.assertEqual(cell.status, LockerCellStatus.VACANT)

            unit = await db.get(InventoryUnit, unit_id)
            self.assertEqual(unit.status, InventoryStatus.MAINTENANCE)
            self.assertIsNone(unit.locker_cell_id)

            movements = (
                await db.scalars(
                    select(InventoryMovement).where(
                        InventoryMovement.inventory_unit_id == unit_id,
                        InventoryMovement.reason == "admin_take_for_service",
                    )
                )
            ).all()
            self.assertEqual(len(movements), 1)
            self.assertEqual(movements[0].to_status, InventoryStatus.MAINTENANCE)
            self.assertEqual(movements[0].comment, "починить корпус")

            audits = (
                await db.scalars(
                    select(AdminAuditEvent).where(
                        AdminAuditEvent.action == "inventory.take_for_service"
                    )
                )
            ).all()
            self.assertEqual(len(audits), 1)

    async def test_take_for_service_with_target_status_damaged(self):
        async with TestSessionLocal() as db:
            await inventory_router.place_product_in_cell(
                _make_request(),
                self.cell_id,
                AdminPlaceProductInCellPayload(productId=self.product_id),
                db,
            )

        async with TestSessionLocal() as db:
            await inventory_router.take_cell_for_service(
                _make_request(),
                self.cell_id,
                AdminTakeForServicePayload(targetStatus="damaged"),
                db,
            )

        async with TestSessionLocal() as db:
            unit = (
                await db.execute(
                    select(InventoryUnit).where(InventoryUnit.product_id == self.product_id)
                )
            ).scalar_one()
            self.assertEqual(unit.status, InventoryStatus.DAMAGED)

    async def test_confirm_ready_marks_unit_available(self):
        async with TestSessionLocal() as db:
            await inventory_router.place_product_in_cell(
                _make_request(),
                self.cell_id,
                AdminPlaceProductInCellPayload(productId=self.product_id),
                db,
            )

        async with TestSessionLocal() as db:
            unit = (
                await db.execute(
                    select(InventoryUnit).where(InventoryUnit.locker_cell_id == self.cell_id)
                )
            ).scalar_one()
            unit.status = InventoryStatus.AWAITING_CONFIRMATION
            await db.commit()
            unit_id = unit.id

        async with TestSessionLocal() as db:
            response = await inventory_router.confirm_inventory_ready(
                _make_request(),
                AdminConfirmInventoryReadyPayload(cellId=self.cell_id, comment="проверено"),
                db,
            )
            self.assertEqual(response["data"]["cell"]["currentUnit"]["status"], InventoryStatus.AVAILABLE.value)

        async with TestSessionLocal() as db:
            unit = await db.get(InventoryUnit, unit_id)
            self.assertEqual(unit.status, InventoryStatus.AVAILABLE)
            self.assertIsNotNone(unit.last_check_at)

            movements = (
                await db.scalars(
                    select(InventoryMovement).where(
                        InventoryMovement.inventory_unit_id == unit_id,
                        InventoryMovement.reason == "admin_confirm_ready",
                    )
                )
            ).all()
            self.assertEqual(len(movements), 1)
            self.assertEqual(movements[0].comment, "проверено")
            self.assertEqual(movements[0].performed_by_admin_id, self.admin_id)

            audits = (
                await db.scalars(
                    select(AdminAuditEvent).where(
                        AdminAuditEvent.action == "inventory.confirm_ready"
                    )
                )
            ).all()
            self.assertEqual(len(audits), 1)

    async def test_confirm_ready_rejects_wrong_status(self):
        async with TestSessionLocal() as db:
            await inventory_router.place_product_in_cell(
                _make_request(),
                self.cell_id,
                AdminPlaceProductInCellPayload(productId=self.product_id),
                db,
            )

        async with TestSessionLocal() as db:
            with self.assertRaises(Exception) as ctx:
                await inventory_router.confirm_inventory_ready(
                    _make_request(),
                    AdminConfirmInventoryReadyPayload(cellId=self.cell_id),
                    db,
                )
            self.assertEqual(getattr(ctx.exception, "status_code", None), 409)

    async def test_take_for_service_on_empty_cell_returns_404(self):
        async with TestSessionLocal() as db:
            with self.assertRaises(Exception) as ctx:
                await inventory_router.take_cell_for_service(
                    _make_request(),
                    self.cell_id,
                    AdminTakeForServicePayload(),
                    db,
                )
            self.assertEqual(getattr(ctx.exception, "status_code", None), 404)

    async def test_test_open_rejects_cell_without_external_id(self):
        async with TestSessionLocal() as db:
            cell = await db.get(LockerCell, self.cell_id)
            cell.external_cell_id = None
            await db.commit()

        async with TestSessionLocal() as db:
            with self.assertRaises(Exception) as ctx:
                await inventory_router.test_open_cell(_make_request(), self.cell_id, db)
            self.assertEqual(getattr(ctx.exception, "status_code", None), 400)

    async def test_test_open_reports_machine_offline(self):
        async def fake_snapshot(serial: str):
            return {"online": False, "cells": {"A1": {"state": "vacant", "open": False}}}

        with patch(
            "backend.routers.admin.inventory.fetch_machine_snapshot",
            side_effect=fake_snapshot,
        ):
            async with TestSessionLocal() as db:
                response = await inventory_router.test_open_cell(
                    _make_request(), self.cell_id, db
                )
        data = response["data"]
        self.assertFalse(data["ok"])
        self.assertEqual(data["result"], "machine_offline")

        async with TestSessionLocal() as db:
            audits = (
                await db.scalars(
                    select(AdminAuditEvent).where(
                        AdminAuditEvent.action == "inventory.test_open"
                    )
                )
            ).all()
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].payload_json.get("result"), "machine_offline")

    async def test_test_open_reports_opened_when_cell_becomes_open(self):
        snapshots = [
            {"online": True, "cells": {"A1": {"state": "vacant", "open": False}}},
            {"online": True, "cells": {"A1": {"state": "vacant", "open": False}}},
            {"online": True, "cells": {"A1": {"state": "vacant", "open": True}}},
        ]
        call_count = {"value": 0}

        async def fake_snapshot(serial: str):
            idx = min(call_count["value"], len(snapshots) - 1)
            call_count["value"] += 1
            return snapshots[idx]

        async def fast_sleep(_seconds):
            return None

        async def fake_open(db, *, locker_id, cell_id):
            return None

        with patch(
            "backend.routers.admin.inventory.fetch_machine_snapshot",
            side_effect=fake_snapshot,
        ), patch(
            "backend.routers.admin.inventory.admin_trigger_open_cell",
            side_effect=fake_open,
        ), patch(
            "backend.routers.admin.inventory.asyncio.sleep",
            side_effect=fast_sleep,
        ):
            async with TestSessionLocal() as db:
                response = await inventory_router.test_open_cell(
                    _make_request(), self.cell_id, db
                )
        data = response["data"]
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"], "opened")
        self.assertTrue(data["openAfter"])
        self.assertGreaterEqual(data["pollAttempts"], 1)

    async def test_test_open_reports_not_opened_when_cell_stays_closed(self):
        async def fake_snapshot(serial: str):
            return {"online": True, "cells": {"A1": {"state": "vacant", "open": False}}}

        async def fast_sleep(_seconds):
            return None

        async def fake_open(db, *, locker_id, cell_id):
            return None

        with patch(
            "backend.routers.admin.inventory.fetch_machine_snapshot",
            side_effect=fake_snapshot,
        ), patch(
            "backend.routers.admin.inventory.admin_trigger_open_cell",
            side_effect=fake_open,
        ), patch(
            "backend.routers.admin.inventory.asyncio.sleep",
            side_effect=fast_sleep,
        ):
            async with TestSessionLocal() as db:
                response = await inventory_router.test_open_cell(
                    _make_request(), self.cell_id, db
                )
        data = response["data"]
        self.assertFalse(data["ok"])
        self.assertEqual(data["result"], "not_opened")
        self.assertFalse(data["openAfter"])

    async def test_test_open_reports_open_failed(self):
        from backend.utils.esi_client import EsiOpenError

        async def fake_snapshot(serial: str):
            return {"online": True, "cells": {"A1": {"state": "vacant", "open": False}}}

        async def fake_open(db, *, locker_id, cell_id):
            raise EsiOpenError("ESI_OPEN_FAILED")

        with patch(
            "backend.routers.admin.inventory.fetch_machine_snapshot",
            side_effect=fake_snapshot,
        ), patch(
            "backend.routers.admin.inventory.admin_trigger_open_cell",
            side_effect=fake_open,
        ):
            async with TestSessionLocal() as db:
                response = await inventory_router.test_open_cell(
                    _make_request(), self.cell_id, db
                )
        data = response["data"]
        self.assertFalse(data["ok"])
        self.assertEqual(data["result"], "open_failed")

        async with TestSessionLocal() as db:
            audit = (
                await db.scalars(
                    select(AdminAuditEvent).where(
                        AdminAuditEvent.action == "inventory.test_open"
                    )
                )
            ).all()[-1]
            self.assertEqual(audit.payload_json.get("result"), "open_failed")
            self.assertEqual(audit.payload_json.get("esiError"), "ESI_OPEN_FAILED")


if __name__ == "__main__":
    unittest.main()
