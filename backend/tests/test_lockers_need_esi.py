"""Постамат без ESI не продаёт аренду.

За постаматом с провайдером не ``esi`` нет железа: команды уходят в стаб,
PIN ничего не откроет. «СПб Невский» был таким и с июня по октябрь 2026
принимал оплаты. На проде (ESI_DEV_STUB выключен) такой постамат нельзя
включить в админке, по нему нельзя посчитать цену, создать бронь или
выдать PIN, а синхронизация каталога всегда держит его выключенным.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import select

TEST_DB_PATH = os.path.abspath(f"./backend/tests/test_lockers_need_esi_{uuid4().hex}.sqlite")
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
os.environ["ESI_DEV_STUB"] = "false"
os.environ["UPLOAD_DEV_STUB"] = "true"

from backend.main import app  # noqa: E402
from backend.core.database import Base, SessionLocal, engine, get_db  # noqa: E402
from backend.core.settings import settings  # noqa: E402
from backend.models.admin_account import AdminAccount  # noqa: E402
from backend.models.auth_session import AuthSession  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    AdminRole,
    AuthPlatform,
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
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
from backend.routers.admin import lockers as admin_lockers  # noqa: E402
from backend.schemas.admin_panel_schemas import (  # noqa: E402
    AdminCreateLockerPayload,
    AdminUpdateLockerPayload,
)
from backend.utils.admin_auth_utils import hash_password  # noqa: E402
from backend.utils.auth_utils import create_access_token  # noqa: E402
from backend.utils.reservation_auto_confirm import auto_confirm_paid_reservations  # noqa: E402


def _admin_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"user-agent", b"pytest")],
            "path": "/api/admin/lockers",
            "client": ("127.0.0.1", 0),
        }
    )


async def _override_get_db():
    async with SessionLocal() as db:
        yield db


class LockersNeedEsiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings.ESI_DEV_STUB = False
        settings.YOOKASSA_DEV_STUB = True
        self._previous_get_db = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = _override_get_db
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            city = City(name="SPb", slug="spb", timezone="Europe/Moscow")
            category = ProductCategory(name="Cat", slug="cat", is_active=True, sort_order=0)
            admin = AdminAccount(
                name="Root", login="root", role=AdminRole.SUPER_ADMIN,
                password_hash=hash_password("irrelevant"),
            )
            user = User(phone="+79990000119", verification_status=VerificationStatus.APPROVED)
            db.add_all([city, category, admin, user])
            await db.flush()
            # Как «СПб Невский» до октября: seed, но ONLINE (данные из прошлого).
            fake = LockerLocation(
                city_id=city.id, name="Nevsky", address="x", status=LockerStatus.ONLINE,
                external_provider="seed", external_locker_id="seed-spb-nevsky",
            )
            product = Product(category_id=category.id, name="Vacuum", slug="vacuum", is_active=True)
            db.add_all([fake, product])
            await db.flush()
            cell = LockerCell(
                locker_id=fake.id, label="M-C1", external_cell_id="M-C1",
                status=LockerCellStatus.OCCUPIED, supports_return=True,
            )
            plan = PricePlan(
                product_id=product.id, name="1 day", duration_type="day", duration_value=1,
                base_amount=Decimal("790.00"), currency="RUB", is_active=True,
            )
            db.add_all([cell, plan])
            await db.flush()
            unit = InventoryUnit(
                product_id=product.id, locker_cell_id=cell.id, status=InventoryStatus.AVAILABLE,
                serial_number="SN-1",
            )
            session = AuthSession(
                user_id=user.id, refresh_token_hash=uuid4().hex, platform=AuthPlatform.WEB,
                expires_at=now + timedelta(days=1),
            )
            db.add_all([unit, session])
            await db.commit()
            self.ids = {
                "city": city.id, "fake": fake.id, "product": product.id, "plan": plan.id,
                "unit": unit.id, "user": user.id, "session": session.id, "admin": admin.id,
            }

        async def fake_get_current_admin(request, db):
            return await db.get(AdminAccount, self.ids["admin"]), None

        self.admin_patch = patch.object(admin_lockers, "get_current_admin", new=fake_get_current_admin)
        self.admin_patch.start()

    async def asyncTearDown(self):
        self.admin_patch.stop()
        settings.ESI_DEV_STUB = True
        if self._previous_get_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = self._previous_get_db
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        try:
            await engine.dispose()
            if os.path.exists(TEST_DB_PATH):
                os.remove(TEST_DB_PATH)
        except (PermissionError, OSError):
            pass

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def test_no_price_and_no_booking_at_a_locker_without_esi(self):
        token = create_access_token(self.ids["user"], self.ids["session"])
        async with self._client() as client:
            r = await client.get(
                f"/products/{self.ids['product']}/pricing",
                params={"lockerId": str(self.ids["fake"]), "durationValue": 1},
            )
            self.assertEqual(r.status_code, 409, r.text)
            self.assertEqual(r.json()["detail"], "LOCKER_NOT_BOOKABLE")

            r = await client.post(
                "/reservations",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "productId": str(self.ids["product"]),
                    "lockerId": str(self.ids["fake"]),
                    "durationType": "day",
                    "durationValue": 1,
                },
            )
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], "LOCKER_NOT_BOOKABLE")
        async with SessionLocal() as db:
            self.assertIsNone(await db.scalar(select(Reservation.id)))

    async def test_paid_booking_at_a_locker_without_esi_gets_no_pin(self):
        """Бронь из прошлого: оплачена, но PIN в несуществующий постамат не выдаём."""
        async with SessionLocal() as db:
            reservation = Reservation(
                user_id=self.ids["user"], product_id=self.ids["product"],
                inventory_unit_id=self.ids["unit"], locker_id=self.ids["fake"],
                price_plan_id=self.ids["plan"], status=ReservationStatus.PAYMENT_AUTHORIZED,
                duration_type="day", duration_value=1, quoted_amount=Decimal("790.00"),
                preauth_amount=Decimal("790.00"),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=20),
            )
            db.add(reservation)
            await db.flush()
            reservation.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
            await db.commit()

        await auto_confirm_paid_reservations()

        async with SessionLocal() as db:
            self.assertIsNone(await db.scalar(select(Rental.id)))

    async def test_admin_cannot_switch_on_a_locker_without_esi(self):
        async with SessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await admin_lockers.create_admin_locker(
                    _admin_request(),
                    AdminCreateLockerPayload(
                        cityId=self.ids["city"], name="Manual", address="y",
                        status=LockerStatus.ONLINE, externalProvider="manual",
                        externalLockerId="manual-1",
                    ),
                    db,
                )
        self.assertEqual(ctx.exception.status_code, 422)

        async with SessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await admin_lockers.update_admin_locker(
                    _admin_request(), self.ids["fake"],
                    AdminUpdateLockerPayload(status=LockerStatus.ONLINE, name="Nevsky 2"), db,
                )
        self.assertEqual(ctx.exception.status_code, 422)

        # Выключенным такой постамат завести можно, а настоящий ESI — включить.
        async with SessionLocal() as db:
            await admin_lockers.create_admin_locker(
                _admin_request(),
                AdminCreateLockerPayload(
                    cityId=self.ids["city"], name="Manual", address="y",
                    status=LockerStatus.OFFLINE, externalProvider="manual",
                    externalLockerId="manual-1",
                ),
                db,
            )
        async with SessionLocal() as db:
            await admin_lockers.create_admin_locker(
                _admin_request(),
                AdminCreateLockerPayload(
                    cityId=self.ids["city"], name="Real", address="z",
                    status=LockerStatus.ONLINE, externalProvider="esi",
                    externalLockerId="PST_0981",
                ),
                db,
            )
        async with SessionLocal() as db:
            statuses = {
                locker.name: locker.status
                for locker in (await db.scalars(select(LockerLocation))).all()
            }
        self.assertEqual(statuses["Manual"], LockerStatus.OFFLINE)
        self.assertEqual(statuses["Real"], LockerStatus.ONLINE)


if __name__ == "__main__":
    unittest.main()
