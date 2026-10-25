"""Удаление товара в админке.

Раньше эндпоинт стирал товар каскадом, а потом падал: ``get_current_admin``
возвращает пару, а её не распаковывали, и аудит вызывали с чужими
аргументами. Оператор видел 500, хотя товар уже исчез, и в журнале ничего
не оставалось. Теперь товар без истории удаляется с записью в аудит, а
товар с арендами или вещью в ячейке — нет: его выключают.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy import select

TEST_DB_PATH = os.path.abspath(f"./backend/tests/test_admin_product_delete_{uuid4().hex}.sqlite")
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL

from backend.main import app  # noqa: E402,F401
from backend.core.database import Base, SessionLocal, engine  # noqa: E402
from backend.models.admin_account import AdminAccount  # noqa: E402
from backend.models.admin_audit_event import AdminAuditEvent  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    AdminRole,
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    ReservationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.routers.admin import products as admin_products  # noqa: E402
from backend.utils.admin_auth_utils import hash_password  # noqa: E402


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "DELETE",
            "headers": [(b"user-agent", b"pytest")],
            "path": "/api/admin/products/x",
            "client": ("127.0.0.1", 0),
        }
    )


class AdminProductDeleteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            city = City(name="VN", slug="vn", timezone="Europe/Moscow")
            category = ProductCategory(name="Cat", slug="cat", is_active=True, sort_order=0)
            admin = AdminAccount(
                name="Root", login="root", role=AdminRole.SUPER_ADMIN,
                password_hash=hash_password("irrelevant"),
            )
            db.add_all([city, category, admin])
            await db.flush()
            locker = LockerLocation(
                city_id=city.id, name="TRC", address="x", status=LockerStatus.ONLINE,
                external_provider="esi", external_locker_id="PST_1",
            )
            product = Product(category_id=category.id, name="Vacuum", slug="vacuum", is_active=True)
            db.add_all([locker, product])
            await db.flush()
            db.add(
                PricePlan(
                    product_id=product.id, name="1 day", duration_type="day", duration_value=1,
                    base_amount=Decimal("790.00"), currency="RUB", is_active=True,
                )
            )
            await db.commit()
            self.ids = {"admin": admin.id, "product": product.id, "locker": locker.id}

        async def fake_get_current_admin(request, db):
            return await db.get(AdminAccount, self.ids["admin"]), None

        self.admin_patch = patch.object(admin_products, "get_current_admin", new=fake_get_current_admin)
        self.admin_patch.start()

    async def asyncTearDown(self):
        self.admin_patch.stop()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        try:
            await engine.dispose()
            if os.path.exists(TEST_DB_PATH):
                os.remove(TEST_DB_PATH)
        except (PermissionError, OSError):
            pass

    async def _delete(self):
        async with SessionLocal() as db:
            return await admin_products.delete_admin_product(self.ids["product"], _request(), db)

    async def _product_exists(self) -> bool:
        async with SessionLocal() as db:
            return await db.get(Product, self.ids["product"]) is not None

    async def test_product_without_history_is_deleted_and_audited(self):
        async with SessionLocal() as db:
            db.add(InventoryUnit(product_id=self.ids["product"], status=InventoryStatus.AVAILABLE))
            await db.commit()

        payload = await self._delete()

        self.assertTrue(payload["data"]["deleted"])
        self.assertFalse(await self._product_exists())
        async with SessionLocal() as db:
            self.assertIsNone(await db.scalar(select(InventoryUnit.id)))
            self.assertIsNone(await db.scalar(select(PricePlan.id)))
            event = await db.scalar(select(AdminAuditEvent).where(AdminAuditEvent.action == "product.delete"))
        self.assertIsNotNone(event)
        self.assertEqual(event.resource_id, self.ids["product"])

    async def test_product_with_a_booking_is_kept(self):
        async with SessionLocal() as db:
            user = User(phone="+79990000119")
            unit = InventoryUnit(product_id=self.ids["product"], status=InventoryStatus.AVAILABLE)
            db.add_all([user, unit])
            await db.flush()
            plan_id = await db.scalar(select(PricePlan.id))
            db.add(
                Reservation(
                    user_id=user.id, product_id=self.ids["product"], inventory_unit_id=unit.id,
                    locker_id=self.ids["locker"], price_plan_id=plan_id,
                    status=ReservationStatus.CANCELLED, duration_type="day", duration_value=1,
                    quoted_amount=Decimal("790.00"), preauth_amount=Decimal("790.00"),
                    expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                )
            )
            await db.commit()

        with self.assertRaises(HTTPException) as ctx:
            await self._delete()
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertTrue(await self._product_exists())

    async def test_product_with_an_item_in_a_locker_is_kept(self):
        async with SessionLocal() as db:
            cell = LockerCell(
                locker_id=self.ids["locker"], label="A1", external_cell_id="1",
                status=LockerCellStatus.OCCUPIED, supports_return=True,
            )
            db.add(cell)
            await db.flush()
            db.add(
                InventoryUnit(
                    product_id=self.ids["product"], locker_cell_id=cell.id,
                    status=InventoryStatus.AVAILABLE,
                )
            )
            await db.commit()

        with self.assertRaises(HTTPException) as ctx:
            await self._delete()
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertTrue(await self._product_exists())


if __name__ == "__main__":
    unittest.main()
