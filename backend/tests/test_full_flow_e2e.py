"""
End-to-end happy-path: регистрация -> верификация -> бронь -> оплата (stub) ->
confirm -> open-cell -> ESI pickup webhook -> active.

Гоняется через ASGI in-memory транспорт, без живых серверов и сети.
SQLite на диске (file:) чтобы и подменённый get_db, и фоновые
SessionLocal-ы reconcile/overdue использовали одну и ту же БД.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Жестко перекрываем DSN ДО импорта приложения, чтобы все singleton'ы
# (engine, SessionLocal, фоновый scheduler) видели наш SQLite.
TEST_DB_PATH = os.path.abspath(f"./backend/tests/test_full_flow_e2e_{uuid4().hex}.sqlite")
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
os.environ["ESI_DEV_STUB"] = "true"
os.environ["UPLOAD_DEV_STUB"] = "true"

from backend.main import app  # noqa: E402
from backend.core import database as core_db  # noqa: E402
from backend.core.database import Base, get_db  # noqa: E402
from backend.core.settings import settings  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    PaymentStatus,
    PaymentType,
    RentalStatus,
    ReservationStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.payment import Payment  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.rental import Rental  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.esi_webhook_handler import process_esi_webhook_payload  # noqa: E402


# --- Тестовый engine, который заменит SessionLocal приложения ---
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def override_get_db():
    async with TestSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db


def _envelope(resp: httpx.Response):
    """Достаём data/{...} из стандартного envelope."""
    body = resp.json()
    return body.get("data", body)


class FullFlowE2ETests(unittest.IsolatedAsyncioTestCase):
    """Прокатываем happy-path от регистрации до получения товара."""

    async def asyncSetUp(self):
        # Удаляем БД от прошлых прогонов
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

        # Гарантируем, что settings и SessionLocal внутри приложения
        # смотрят на нашу тестовую БД.
        settings.YOOKASSA_DEV_STUB = True
        settings.ESI_DEV_STUB = True
        settings.UPLOAD_DEV_STUB = True

        self._session_local_patch = patch.object(core_db, "SessionLocal", TestSessionLocal)
        self._session_local_patch.start()

        # Создаём схему
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Сидим минимальный каталог: город, категория, продукт, постамат, ячейка,
        # инвентарь, прайс
        async with TestSessionLocal() as db:
            self.city_id = uuid4()
            self.category_id = uuid4()
            self.product_id = uuid4()
            self.locker_id = uuid4()
            self.cell_id = uuid4()
            self.unit_id = uuid4()
            self.price_plan_id = uuid4()

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
                        name="PS5",
                        slug="ps5",
                        is_active=True,
                    ),
                    LockerLocation(
                        id=self.locker_id,
                        city_id=self.city_id,
                        name="Locker A",
                        address="ул. Пушкина, 1",
                        status=LockerStatus.ONLINE,
                        external_provider="esi",
                        external_locker_id="LOCKER-001",
                    ),
                    LockerCell(
                        id=self.cell_id,
                        locker_id=self.locker_id,
                        label="A1",
                        external_cell_id="A1",
                        status=LockerCellStatus.OCCUPIED,
                        supports_return=True,
                    ),
                    InventoryUnit(
                        id=self.unit_id,
                        product_id=self.product_id,
                        locker_cell_id=self.cell_id,
                        status=InventoryStatus.AVAILABLE,
                        serial_number="SN-001",
                    ),
                    PricePlan(
                        id=self.price_plan_id,
                        product_id=self.product_id,
                        name="1 day",
                        duration_type="day",
                        duration_value=1,
                        base_amount=Decimal("100.00"),
                        currency="RUB",
                        is_active=True,
                    ),
                ]
            )
            await db.commit()

        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self._session_local_patch.stop()
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await test_engine.dispose()
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

    async def _approve_user_in_db(self, user_id_str: str) -> None:
        """Юзер должен быть APPROVED, иначе бронь блокируется."""
        from uuid import UUID

        async with TestSessionLocal() as db:
            user = await db.get(User, UUID(user_id_str))
            assert user is not None
            user.verification_status = VerificationStatus.APPROVED
            await db.commit()

    async def test_full_happy_path(self):
        # 1) Регистрация: dev-login по телефону
        r = await self.client.post(
            "/auth/dev-login", json={"phone": "+79991112233"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        login = _envelope(r)
        access_token = login["accessToken"]
        user_id = login["user"]["id"]
        self.assertEqual(login["user"]["verificationStatus"], "draft")

        auth_h = {"Authorization": f"Bearer {access_token}"}

        # 2) Профиль доступен
        r = await self.client.get("/me", headers=auth_h)
        self.assertEqual(r.status_code, 200, r.text)

        # 3) Подделываем APPROVED-верификацию (тест верификации
        #    через docs/upload отдельно покрыт в test_verification_flow.py)
        await self._approve_user_in_db(user_id)

        # 4) Каталог: видим товар
        r = await self.client.get("/products", headers=auth_h)
        self.assertEqual(r.status_code, 200, r.text)
        products = _envelope(r).get("products") or _envelope(r).get("items") or []
        self.assertTrue(
            any(str(p.get("id")) == str(self.product_id) for p in products),
            f"Product not in catalog: {products}",
        )

        # 5) Quote
        r = await self.client.post(
            "/reservations/quote",
            headers=auth_h,
            json={
                "productId": str(self.product_id),
                "lockerId": str(self.locker_id),
                "durationType": "day",
                "durationValue": 1,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        quote = _envelope(r)["quote"]
        self.assertEqual(quote["currency"], "RUB")
        self.assertEqual(quote["quotedAmount"], 10000)  # 100.00 RUB -> minor units

        # 6) Создаём бронь (Reservation: AWAITING_PAYMENT, Inventory: RESERVED)
        r = await self.client.post(
            "/reservations",
            headers=auth_h,
            json={
                "productId": str(self.product_id),
                "lockerId": str(self.locker_id),
                "durationType": "day",
                "durationValue": 1,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        reservation = _envelope(r)["reservation"]
        reservation_id = reservation["id"]
        self.assertEqual(reservation["status"], "awaiting_payment")

        # Проверим в БД, что юнит зарезервирован
        async with TestSessionLocal() as db:
            unit = await db.get(InventoryUnit, self.unit_id)
            self.assertEqual(unit.status, InventoryStatus.RESERVED)

        # 7) Платёж: preauth (с YooKassa в stub-режиме)
        r = await self.client.post(
            "/payments/preauth",
            headers=auth_h,
            json={"reservationId": reservation_id},
        )
        self.assertEqual(r.status_code, 200, r.text)
        prep = _envelope(r)
        payment_id = prep["payment"]["id"]
        self.assertIn("confirmationUrl", prep["confirmation"])

        # 8) Симулируем callback от YooKassa: переводим payment в AUTHORIZED
        r = await self.client.post(
            f"/payments/{payment_id}/authorize-dev-stub",
            headers=auth_h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        authorized = _envelope(r)
        self.assertEqual(authorized["payment"]["status"], "authorized")

        # Резервация должна перейти в payment_authorized
        async with TestSessionLocal() as db:
            from uuid import UUID

            res_db = await db.get(Reservation, UUID(reservation_id))
            self.assertEqual(res_db.status, ReservationStatus.PAYMENT_AUTHORIZED)

        # 9) Confirm reservation -> создаётся Rental(PICKUP_READY) + PIN
        r = await self.client.post(
            f"/reservations/{reservation_id}/confirm",
            headers=auth_h,
            json={"paymentId": payment_id},
        )
        self.assertEqual(r.status_code, 200, r.text)
        rental = _envelope(r)["rental"]
        rental_id = rental["id"]
        self.assertEqual(rental["status"], "pickup_ready")
        self.assertTrue(rental["pickupPin"])
        pickup_pin = rental["pickupPin"]

        # 10) Открыть ячейку (admin_trigger_open_cell -> ESI stub success)
        r = await self.client.post(
            f"/me/rentals/{rental_id}/open-cell",
            headers=auth_h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        opened = _envelope(r)["rental"]
        self.assertEqual(opened["status"], "pickup_opened")

        # 11) Клиент подтверждает, что забрал товар (confirm-pickup)
        r = await self.client.post(
            f"/me/rentals/{rental_id}/confirm-pickup",
            headers=auth_h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_envelope(r)["rental"]["status"], "active")

        # 12) Проверяем итог: товар у клиента, ячейка пуста
        async with TestSessionLocal() as db:
            from uuid import UUID

            rental_db = await db.get(Rental, UUID(rental_id))
            unit_db = await db.get(InventoryUnit, self.unit_id)
            cell_db = await db.get(LockerCell, self.cell_id)

            self.assertEqual(rental_db.status, RentalStatus.ACTIVE)
            self.assertEqual(unit_db.status, InventoryStatus.RENTED)
            self.assertIsNone(unit_db.locker_cell_id)
            self.assertEqual(cell_db.status, LockerCellStatus.VACANT)

        # 13) Финальная проверка: клиент видит свою активную аренду
        r = await self.client.get("/me/rentals", headers=auth_h)
        self.assertEqual(r.status_code, 200, r.text)
        rentals_data = _envelope(r)
        rentals = rentals_data.get("rentals") or rentals_data.get("items") or []
        self.assertTrue(
            any(item.get("id") == rental_id for item in rentals),
            f"Rental not in /me/rentals: {rentals}",
        )

        # 14) Клиент инициирует возврат в тот же постамат
        r = await self.client.post(
            f"/me/rentals/{rental_id}/return-request",
            headers=auth_h,
            json={"lockerId": str(self.locker_id)},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return_payload = _envelope(r)["return"]
        self.assertEqual(return_payload["status"], "locker_opened")

        # 15) Клиент подтверждает, что положил товар обратно (confirm-return)
        with patch("backend.routers.me.notify_inventory_awaiting_confirmation") as notify_mock:
            r = await self.client.post(
                f"/me/rentals/{rental_id}/confirm-return",
                headers=auth_h,
            )
            notify_mock.assert_called_once()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_envelope(r)["rental"]["status"], "completed")

        async with TestSessionLocal() as db:
            from uuid import UUID

            rental_db = await db.get(Rental, UUID(rental_id))
            unit_db = await db.get(InventoryUnit, self.unit_id)
            cell_db = await db.get(LockerCell, self.cell_id)

            self.assertEqual(rental_db.status, RentalStatus.COMPLETED)
            self.assertEqual(unit_db.status, InventoryStatus.AWAITING_CONFIRMATION)
            self.assertEqual(unit_db.locker_cell_id, self.cell_id)
            self.assertEqual(cell_db.status, LockerCellStatus.OCCUPIED)

        print(
            f"\n[E2E OK] user={user_id} reservation={reservation_id} "
            f"payment={payment_id} rental={rental_id} pin={pickup_pin}"
        )


if __name__ == "__main__":
    unittest.main()
