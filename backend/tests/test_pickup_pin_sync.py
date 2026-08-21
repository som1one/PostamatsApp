"""PIN и постамат: код должен существовать в железе в момент выдачи.

Код попадал в постамат один раз — при подтверждении брони. Сброс постамата
(или любой перевод ячейки в свободную, при котором ESI затирает pin)
оставлял клиента с кодом, которого на клавиатуре уже нет.

Здесь проверяется:
  * `confirm-pickup` перезаписывает PIN в ячейке перед выдачей клиенту;
  * `esi_reconcile` возвращает забытый PIN сам, без обращения в поддержку;
  * ни один из этих путей НЕ открывает ячейку — уходит только `/set-cell`,
    команда `/open-cell` не вызывается ни разу.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DB_PATH = os.path.abspath(f"./backend/tests/test_pickup_pin_{uuid4().hex}.sqlite")
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
# ESI-стаб выключен намеренно: нам нужен реальный путь построения запроса,
# сам HTTP при этом замокан на уровне `_esi_post`.
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
    LockerCellStatus,
    LockerStatus,
    RentalStatus,
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
from backend.models.rental_event import RentalEvent  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.auth_utils import create_access_token  # noqa: E402
from backend.utils.esi_reconcile import reconcile_esi_and_returns  # noqa: E402

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

SERIAL = "ESI-TEST-1"
EXTERNAL_CELL_ID = "2"
PICKUP_PIN = "5110"


def _opened_cell_paths(esi_post: AsyncMock) -> list[str]:
    """Пути, которыми ESI просили ОТКРЫТЬ ячейку. Должен быть пустым."""
    return [
        call.args[0]
        for call in esi_post.await_args_list
        if call.args and str(call.args[0]).startswith("/open-cell")
    ]


def _set_cell_calls(esi_post: AsyncMock) -> list[tuple[str, dict]]:
    return [
        (call.args[0], call.kwargs.get("payload") or {})
        for call in esi_post.await_args_list
        if call.args and str(call.args[0]).startswith("/set-cell")
    ]


class PickupPinSyncTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings.YOOKASSA_DEV_STUB = True
        settings.ESI_DEV_STUB = False
        settings.ESI_BASE_URL = "https://esi.test"
        settings.UPLOAD_DEV_STUB = True

        self._session_local_patch = patch.object(core_db, "SessionLocal", TestSessionLocal)
        self._session_local_patch.start()

        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        self.city_id = uuid4()
        self.category_id = uuid4()
        self.product_id = uuid4()
        self.plan_id = uuid4()
        self.user_id = uuid4()
        self.locker_id = uuid4()
        self.cell_id = uuid4()
        self.unit_id = uuid4()
        self.reservation_id = uuid4()
        self.rental_id = uuid4()
        self.session_id = uuid4()

        now = datetime.now(timezone.utc)
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
                        id=self.plan_id,
                        product_id=self.product_id,
                        name="1 day",
                        duration_type="day",
                        duration_value=1,
                        base_amount=Decimal("1120.00"),
                        currency="RUB",
                        is_active=True,
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
                        external_locker_id=SERIAL,
                    ),
                    LockerCell(
                        id=self.cell_id,
                        locker_id=self.locker_id,
                        label="A2",
                        external_cell_id=EXTERNAL_CELL_ID,
                        status=LockerCellStatus.RESERVED,
                        supports_return=True,
                    ),
                    InventoryUnit(
                        id=self.unit_id,
                        product_id=self.product_id,
                        locker_cell_id=self.cell_id,
                        status=InventoryStatus.RESERVED,
                        serial_number=f"SN-{uuid4().hex[:6]}",
                    ),
                    Reservation(
                        id=self.reservation_id,
                        user_id=self.user_id,
                        product_id=self.product_id,
                        inventory_unit_id=self.unit_id,
                        locker_id=self.locker_id,
                        price_plan_id=self.plan_id,
                        status=ReservationStatus.CONFIRMED,
                        duration_type="day",
                        duration_value=1,
                        quoted_amount=Decimal("1120.00"),
                        expires_at=now + timedelta(hours=2),
                        pickup_at=now - timedelta(hours=3),
                    ),
                    Rental(
                        id=self.rental_id,
                        user_id=self.user_id,
                        reservation_id=self.reservation_id,
                        inventory_unit_id=self.unit_id,
                        pickup_locker_id=self.locker_id,
                        status=RentalStatus.PICKUP_READY,
                        pickup_pin=PICKUP_PIN,
                        starts_at=now - timedelta(hours=3),
                        planned_end_at=now + timedelta(hours=21),
                        pickup_expires_at=now + timedelta(hours=6),
                    ),
                ]
            )
            await db.commit()

    async def asyncTearDown(self):
        self._session_local_patch.stop()
        # Файл БД не удаляем: на Windows он ещё удерживается пулом, а между
        # тестами схему всё равно пересоздаёт `drop_all` в setUp.
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

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


class ConfirmPickupWritesPinTests(PickupPinSyncTestBase):
    """«Получить PIN» должен положить код в постамат, не открывая ячейку."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.auth_headers = {
            "Authorization": f"Bearer {create_access_token(self.user_id, self.session_id)}"
        }

    async def _confirm_pickup(self) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                f"/me/rentals/{self.rental_id}/confirm-pickup",
                headers=self.auth_headers,
            )

    async def test_pin_is_written_to_locker_and_cell_is_not_opened(self):
        esi_post = AsyncMock(return_value={})
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.utils.esi_client.is_machine_online", new=AsyncMock(return_value=True)
        ):
            response = await self._confirm_pickup()

        self.assertEqual(response.status_code, 200, response.text)

        set_cell_calls = _set_cell_calls(esi_post)
        self.assertEqual(len(set_cell_calls), 1, set_cell_calls)
        path, payload = set_cell_calls[0]
        self.assertEqual(path, f"/set-cell/{SERIAL}/{EXTERNAL_CELL_ID}")
        self.assertEqual(payload.get("pin"), PICKUP_PIN)
        self.assertEqual(payload.get("state"), "assigned")

        # Главное требование: выдача кода не должна открывать дверцу.
        self.assertEqual(_opened_cell_paths(esi_post), [])

        rental = await self._reload_rental()
        self.assertEqual(rental.status, RentalStatus.ACTIVE)
        self.assertEqual(rental.pickup_pin, PICKUP_PIN)

    async def test_rental_does_not_start_when_locker_rejects_the_pin(self):
        """ESI недоступен — код мёртвый, поэтому аренду не стартуем."""

        esi_post = AsyncMock(side_effect=RuntimeError("esi is down"))
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.utils.esi_client.is_machine_online", new=AsyncMock(return_value=True)
        ):
            response = await self._confirm_pickup()

        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(_opened_cell_paths(esi_post), [])

        rental = await self._reload_rental()
        self.assertEqual(rental.status, RentalStatus.PICKUP_READY)

    async def test_offline_locker_answers_with_a_readable_code(self):
        esi_post = AsyncMock(return_value={})
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.utils.esi_client.is_machine_online", new=AsyncMock(return_value=False)
        ):
            response = await self._confirm_pickup()

        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("LOCKER_OFFLINE", response.text)
        self.assertEqual(esi_post.await_args_list, [])

        rental = await self._reload_rental()
        self.assertEqual(rental.status, RentalStatus.PICKUP_READY)


class ReconcileRestoresPinTests(PickupPinSyncTestBase):
    """Сброс постамата не должен требовать обращения в поддержку."""

    def _snapshot(self, *, state: str, is_open: bool = False) -> list[dict]:
        return [
            {
                "serial": SERIAL,
                "cells": {EXTERNAL_CELL_ID: {"state": state, "open": is_open}},
            }
        ]

    async def _run_reconcile(self, snapshot: list[dict]) -> AsyncMock:
        esi_post = AsyncMock(return_value={})
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.utils.esi_reconcile.fetch_machines_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch(
            "backend.utils.esi_reconcile.fetch_machine_snapshot",
            new=AsyncMock(return_value=snapshot[0] if snapshot else None),
        ):
            await reconcile_esi_and_returns()
        return esi_post

    async def test_pin_is_restored_when_locker_forgot_it(self):
        esi_post = await self._run_reconcile(self._snapshot(state="unassigned"))

        set_cell_calls = _set_cell_calls(esi_post)
        self.assertEqual(len(set_cell_calls), 1, set_cell_calls)
        path, payload = set_cell_calls[0]
        self.assertEqual(path, f"/set-cell/{SERIAL}/{EXTERNAL_CELL_ID}")
        self.assertEqual(payload.get("pin"), PICKUP_PIN)
        self.assertEqual(payload.get("state"), "assigned")

        # Восстановление кода не должно открывать дверцу.
        self.assertEqual(_opened_cell_paths(esi_post), [])

        events = await self._events("pickup_pin_restored")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload_json["externalCellId"], EXTERNAL_CELL_ID)

        async with TestSessionLocal() as db:
            cell = await db.get(LockerCell, self.cell_id)
            self.assertEqual(cell.status, LockerCellStatus.RESERVED)

    async def test_pin_is_left_alone_when_locker_still_holds_it(self):
        esi_post = await self._run_reconcile(self._snapshot(state="assigned"))

        self.assertEqual(_set_cell_calls(esi_post), [])
        self.assertEqual(_opened_cell_paths(esi_post), [])
        self.assertEqual(await self._events("pickup_pin_restored"), [])

    async def test_open_cell_is_never_touched_during_pickup(self):
        """Ячейка открыта — там сейчас идёт выдача, ничего не пишем."""

        esi_post = await self._run_reconcile(
            self._snapshot(state="unassigned", is_open=True)
        )

        self.assertEqual(_set_cell_calls(esi_post), [])
        self.assertEqual(_opened_cell_paths(esi_post), [])

    async def test_pin_is_not_restored_after_the_customer_took_the_item(self):
        """Ячейку уже открывали после появления аренды — товар забрали."""

        async with TestSessionLocal() as db:
            cell = await db.get(LockerCell, self.cell_id)
            cell.last_opened_at = datetime.now(timezone.utc) + timedelta(minutes=1)
            await db.commit()

        esi_post = await self._run_reconcile(self._snapshot(state="unassigned"))

        self.assertEqual(_set_cell_calls(esi_post), [])
        self.assertEqual(await self._events("pickup_pin_restored"), [])

    async def test_pin_is_not_restored_for_a_rental_that_already_started(self):
        async with TestSessionLocal() as db:
            rental = await db.get(Rental, self.rental_id)
            rental.status = RentalStatus.ACTIVE
            await db.commit()

        esi_post = await self._run_reconcile(self._snapshot(state="unassigned"))

        self.assertEqual(_set_cell_calls(esi_post), [])
        self.assertEqual(await self._events("pickup_pin_restored"), [])


if __name__ == "__main__":
    unittest.main()
