"""Продление активной аренды из профиля.

Проверяется:
  * варианты продления считаются от тарифов товара и режутся началом
    следующей брони на тот же экземпляр;
  * `POST /extend` создаёт платёж, а срок сдвигается только после оплаты
    (dev-stub authorize) — идемпотентно;
  * просроченная аренда после продления возвращается в ACTIVE;
  * продление за начало следующей брони отклоняется (EXTENSION_CONFLICT);
  * ГЛАВНОЕ: за весь флоу продления в ESI не уходит НИ ОДНОГО запроса —
    ни `/open-cell`, ни `/set-cell`. Ячейки постамата не трогаются.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DB_PATH = os.path.abspath(f"./backend/tests/test_rental_extension_{uuid4().hex}.sqlite")
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
# ESI-стаб выключен намеренно: если бы продление пыталось что-то отправить
# в постамат, запрос дошёл бы до замоканного `_esi_post` и тест это увидел.
os.environ["ESI_DEV_STUB"] = "false"
os.environ["ESI_BASE_URL"] = "https://esi.test"
os.environ["UPLOAD_DEV_STUB"] = "true"

from backend.main import app  # noqa: E402
from backend.core import database as core_db  # noqa: E402
from backend.core.database import Base, get_db  # noqa: E402
from backend.core.settings import settings  # noqa: E402
from backend.models.auth_session import AuthSession  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    AuthPlatform,
    InventoryStatus,
    LockerStatus,
    PaymentStatus,
    PaymentType,
    RentalStatus,
    ReservationStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.payment import Payment  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.rental import Rental  # noqa: E402
from backend.models.rental_event import RentalEvent  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.auth_utils import create_access_token  # noqa: E402

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


class RentalExtensionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings.YOOKASSA_DEV_STUB = True
        settings.ESI_DEV_STUB = False
        settings.ESI_BASE_URL = "https://esi.test"
        settings.UPLOAD_DEV_STUB = True

        self._session_local_patch = patch.object(core_db, "SessionLocal", TestSessionLocal)
        self._session_local_patch.start()
        # Любое обращение в ESI во время продления — ошибка. Мокаем сам
        # HTTP-слой и в конце каждого теста проверяем, что он не вызывался.
        self.esi_post = AsyncMock(return_value={})
        self._esi_patch = patch("backend.utils.esi_client._esi_post", new=self.esi_post)
        self._esi_patch.start()

        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        self.city_id = uuid4()
        self.category_id = uuid4()
        self.product_id = uuid4()
        self.plan_day_id = uuid4()
        self.plan_week_id = uuid4()
        self.user_id = uuid4()
        self.locker_id = uuid4()
        self.unit_id = uuid4()
        self.rental_id = uuid4()
        self.session_id = uuid4()

        now = datetime.now(timezone.utc)
        self.planned_end = now + timedelta(hours=10)
        async with TestSessionLocal() as db:
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
                        name="Моющий пылесос",
                        slug="washing-vacuum",
                        is_active=True,
                    ),
                    PricePlan(
                        id=self.plan_day_id,
                        product_id=self.product_id,
                        name="1 день",
                        duration_type="day",
                        duration_value=1,
                        base_amount=Decimal("500.00"),
                        currency="RUB",
                        is_active=True,
                        sort_order=0,
                    ),
                    PricePlan(
                        id=self.plan_week_id,
                        product_id=self.product_id,
                        name="Неделя",
                        duration_type="week",
                        duration_value=1,
                        base_amount=Decimal("2500.00"),
                        currency="RUB",
                        is_active=True,
                        sort_order=1,
                    ),
                    User(
                        id=self.user_id,
                        phone="+79991112233",
                        verification_status=VerificationStatus.APPROVED,
                    ),
                    AuthSession(
                        id=self.session_id,
                        user_id=self.user_id,
                        refresh_token_hash=f"hash-{uuid4().hex}",
                        platform=AuthPlatform.WEB,
                        expires_at=now + timedelta(days=30),
                    ),
                    LockerLocation(
                        id=self.locker_id,
                        city_id=self.city_id,
                        name="ТРЦ Тестовый",
                        address="ул. Тестовая, 1",
                        status=LockerStatus.ONLINE,
                        external_provider="esi",
                        external_locker_id="ESI-TEST-1",
                    ),
                    # Товар уже на руках: ячейки за юнитом нет.
                    InventoryUnit(
                        id=self.unit_id,
                        product_id=self.product_id,
                        locker_cell_id=None,
                        status=InventoryStatus.RENTED,
                        serial_number=f"SN-{uuid4().hex[:6]}",
                    ),
                    Rental(
                        id=self.rental_id,
                        user_id=self.user_id,
                        reservation_id=None,
                        inventory_unit_id=self.unit_id,
                        pickup_locker_id=self.locker_id,
                        status=RentalStatus.ACTIVE,
                        pickup_pin="4321",
                        starts_at=now - timedelta(hours=14),
                        planned_end_at=self.planned_end,
                    ),
                ]
            )
            await db.commit()

        self.auth_headers = {
            "Authorization": f"Bearer {create_access_token(self.user_id, self.session_id)}"
        }

    async def asyncTearDown(self):
        # Ключевая гарантия фичи: продление никогда не разговаривает с
        # постаматом. Проверяем во всех тестах разом.
        self.assertEqual(
            self.esi_post.await_args_list,
            [],
            "Продление аренды отправило запрос(ы) в ESI — этого быть не должно",
        )
        self._esi_patch.stop()
        self._session_local_patch.stop()
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    def _client(self) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    async def _reload_rental(self) -> Rental:
        async with TestSessionLocal() as db:
            return await db.get(Rental, self.rental_id)

    async def _events(self, event_type: str) -> list[RentalEvent]:
        async with TestSessionLocal() as db:
            return list(
                (
                    await db.scalars(
                        select(RentalEvent).where(
                            RentalEvent.rental_id == self.rental_id,
                            RentalEvent.event_type == event_type,
                        )
                    )
                ).all()
            )

    async def _extend(self, duration_type="day", duration_value=1) -> httpx.Response:
        async with self._client() as client:
            return await client.post(
                f"/me/rentals/{self.rental_id}/extend",
                headers=self.auth_headers,
                json={"durationType": duration_type, "durationValue": duration_value},
            )

    async def _authorize(self, payment_id: str) -> httpx.Response:
        async with self._client() as client:
            return await client.post(
                f"/payments/{payment_id}/authorize-dev-stub",
                headers=self.auth_headers,
            )

    async def test_options_list_plans_and_barrier(self):
        async with self._client() as client:
            response = await client.get(
                f"/me/rentals/{self.rental_id}/extension-options",
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, 200, response.text)
        extension = response.json()["data"]["extension"]
        self.assertEqual(extension["rentalId"], str(self.rental_id))
        self.assertIsNone(extension["maxEndAt"])
        durations = {(o["durationType"], o["durationValue"]) for o in extension["options"]}
        self.assertEqual(durations, {("day", 1), ("week", 1)})
        self.assertTrue(all(o["available"] for o in extension["options"]))
        day_option = next(o for o in extension["options"] if o["durationType"] == "day")
        self.assertEqual(day_option["amount"], 50000)

    async def test_extension_applies_after_payment_and_is_idempotent(self):
        response = await self._extend("day", 1)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        payment_id = data["payment"]["id"]
        self.assertEqual(data["payment"]["amount"], 50000)

        # До оплаты срок не двигается.
        rental = await self._reload_rental()
        self.assertEqual(
            rental.planned_end_at.replace(tzinfo=timezone.utc), self.planned_end
        )
        self.assertEqual(len(await self._events("extension_requested")), 1)
        self.assertEqual(await self._events("extension_applied"), [])

        auth_response = await self._authorize(payment_id)
        self.assertEqual(auth_response.status_code, 200, auth_response.text)

        rental = await self._reload_rental()
        expected_end = self.planned_end + timedelta(days=1)
        self.assertEqual(rental.planned_end_at.replace(tzinfo=timezone.utc), expected_end)
        self.assertEqual(rental.status, RentalStatus.ACTIVE)
        self.assertEqual(len(await self._events("extension_applied")), 1)

        # Повторная авторизация того же платежа не сдвигает срок ещё раз.
        again = await self._authorize(payment_id)
        self.assertEqual(again.status_code, 200, again.text)
        rental = await self._reload_rental()
        self.assertEqual(rental.planned_end_at.replace(tzinfo=timezone.utc), expected_end)
        self.assertEqual(len(await self._events("extension_applied")), 1)

    async def test_overdue_rental_returns_to_active(self):
        now = datetime.now(timezone.utc)
        async with TestSessionLocal() as db:
            rental = await db.get(Rental, self.rental_id)
            rental.status = RentalStatus.OVERDUE
            rental.overdue_started_at = now - timedelta(hours=2)
            rental.planned_end_at = now - timedelta(hours=2)
            await db.commit()

        response = await self._extend("week", 1)
        self.assertEqual(response.status_code, 200, response.text)
        payment_id = response.json()["data"]["payment"]["id"]

        auth_response = await self._authorize(payment_id)
        self.assertEqual(auth_response.status_code, 200, auth_response.text)

        rental = await self._reload_rental()
        self.assertEqual(rental.status, RentalStatus.ACTIVE)
        self.assertIsNone(rental.overdue_started_at)
        self.assertGreater(rental.planned_end_at.replace(tzinfo=timezone.utc), now)

    async def test_extension_blocked_by_next_reservation(self):
        now = datetime.now(timezone.utc)
        next_pickup = self.planned_end + timedelta(hours=8)
        async with TestSessionLocal() as db:
            db.add(
                Reservation(
                    id=uuid4(),
                    user_id=self.user_id,
                    product_id=self.product_id,
                    inventory_unit_id=self.unit_id,
                    locker_id=self.locker_id,
                    price_plan_id=self.plan_day_id,
                    status=ReservationStatus.PAYMENT_AUTHORIZED,
                    duration_type="day",
                    duration_value=1,
                    quoted_amount=Decimal("500.00"),
                    expires_at=now + timedelta(days=2),
                    pickup_at=next_pickup,
                )
            )
            await db.commit()

        # Сутки не влезают до следующей брони (осталось 8 часов).
        response = await self._extend("day", 1)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("EXTENSION_CONFLICT", response.text)

        # А в списке опций это видно как available=false и maxEndAt.
        async with self._client() as client:
            options_response = await client.get(
                f"/me/rentals/{self.rental_id}/extension-options",
                headers=self.auth_headers,
            )
        extension = options_response.json()["data"]["extension"]
        self.assertIsNotNone(extension["maxEndAt"])
        self.assertTrue(all(not o["available"] for o in extension["options"]))

    async def test_extension_requires_extendable_status(self):
        async with TestSessionLocal() as db:
            rental = await db.get(Rental, self.rental_id)
            rental.status = RentalStatus.COMPLETED
            await db.commit()

        response = await self._extend("day", 1)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("RENTAL_NOT_EXTENDABLE", response.text)

    async def test_foreign_rental_is_forbidden(self):
        other_user_id = uuid4()
        other_session_id = uuid4()
        now = datetime.now(timezone.utc)
        async with TestSessionLocal() as db:
            db.add_all(
                [
                    User(
                        id=other_user_id,
                        phone="+79994445566",
                        verification_status=VerificationStatus.APPROVED,
                    ),
                    AuthSession(
                        id=other_session_id,
                        user_id=other_user_id,
                        refresh_token_hash=f"hash-{uuid4().hex}",
                        platform=AuthPlatform.WEB,
                        expires_at=now + timedelta(days=30),
                    ),
                ]
            )
            await db.commit()

        headers = {
            "Authorization": f"Bearer {create_access_token(other_user_id, other_session_id)}"
        }
        async with self._client() as client:
            response = await client.post(
                f"/me/rentals/{self.rental_id}/extend",
                headers=headers,
                json={"durationType": "day", "durationValue": 1},
            )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_background_reconcile_picks_up_extension_payment(self):
        """Оплата через СБП без возврата на сайт: срок двигает фоновая сверка."""
        response = await self._extend("day", 1)
        self.assertEqual(response.status_code, 200, response.text)
        payment_id = response.json()["data"]["payment"]["id"]

        # Состариваем платёж, чтобы сверка его взяла (min age 60 секунд).
        async with TestSessionLocal() as db:
            payment = await db.get(Payment, UUID(payment_id))
            self.assertEqual(payment.type, PaymentType.EXTRA_CHARGE)
            payment.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            await db.commit()

        from backend.utils import payment_reconcile

        with patch.object(
            payment_reconcile, "SessionLocal", TestSessionLocal
        ), patch(
            "backend.utils.yookassa_service.fetch_yookassa_payment_status",
            new=AsyncMock(return_value="succeeded"),
        ):
            await payment_reconcile.reconcile_pending_payments()

        rental = await self._reload_rental()
        expected_end = self.planned_end + timedelta(days=1)
        self.assertEqual(rental.planned_end_at.replace(tzinfo=timezone.utc), expected_end)
        async with TestSessionLocal() as db:
            payment = await db.get(Payment, UUID(payment_id))
            self.assertEqual(payment.status, PaymentStatus.CAPTURED)


if __name__ == "__main__":
    unittest.main()
