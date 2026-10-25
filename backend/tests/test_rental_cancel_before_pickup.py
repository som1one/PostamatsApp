"""Отмена аренды, которую ещё не забрали: деньги, ячейка и PIN.

Три пути — оператор («Снять аренду»), шедулер (не забрали за 3 часа) и
клиент (отмена заранее) — должны одинаково:

  * вернуть клиенту деньги, а не получилось — аренду не снимать;
  * оставить ячейку «занятой»: вещь внутри;
  * сменить PIN ячейки в постамате на новый, чтобы старый код клиента
    больше её не открывал, — и ничего не перебить: чужой код в ячейке не
    трогать, дверцу не открывать (только ``/set-cell``).

А «Снять» вещь, которая уже у клиента, оператор не может.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import select

TEST_DB_PATH = os.path.abspath(f"./backend/tests/test_rental_cancel_{uuid4().hex}.sqlite")
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
# Нужен настоящий путь построения команд постамату; сам HTTP замокан.
os.environ["ESI_DEV_STUB"] = "false"
os.environ["ESI_BASE_URL"] = "https://esi.test"
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
from backend.models.rental_event import RentalEvent  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.routers.admin import rentals as admin_rentals  # noqa: E402
from backend.utils.admin_auth_utils import hash_password  # noqa: E402
from backend.utils.auth_utils import create_access_token  # noqa: E402
from backend.utils.rental_cancellation import reset_pin_after_pickup_cancel  # noqa: E402
from backend.utils.rental_pickup_expiry import expire_stale_pickup_rentals  # noqa: E402

SERIAL = "ESI-TEST-1"
EXTERNAL_CELL_ID = "2"
OLD_PIN = "5110"


def _set_cell_calls(esi_post: AsyncMock) -> list[tuple[str, dict]]:
    return [
        (call.args[0], call.kwargs.get("payload") or {})
        for call in esi_post.await_args_list
        if call.args and str(call.args[0]).startswith("/set-cell")
    ]


def _opened_cell_paths(esi_post: AsyncMock) -> list[str]:
    return [
        call.args[0]
        for call in esi_post.await_args_list
        if call.args and str(call.args[0]).startswith("/open-cell")
    ]


def _admin_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"user-agent", b"pytest")],
            "path": "/api/admin/rentals/x/cancel",
            "client": ("127.0.0.1", 0),
        }
    )


async def _override_get_db():
    async with SessionLocal() as db:
        yield db


class CancelBeforePickupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings.YOOKASSA_DEV_STUB = True
        settings.ESI_DEV_STUB = False
        settings.ESI_BASE_URL = "https://esi.test"
        self._previous_get_db = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = _override_get_db

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            city = City(name="VN", slug="vn", timezone="Europe/Moscow")
            category = ProductCategory(name="Cat", slug="cat", is_active=True, sort_order=0)
            admin = AdminAccount(
                name="Root", login="root", role=AdminRole.SUPER_ADMIN,
                password_hash=hash_password("irrelevant"),
            )
            user = User(phone="+79990000119", verification_status=VerificationStatus.APPROVED)
            db.add_all([city, category, admin, user])
            await db.flush()
            locker = LockerLocation(
                city_id=city.id, name="TRC", address="x", status=LockerStatus.ONLINE,
                external_provider="esi", external_locker_id=SERIAL,
            )
            product = Product(category_id=category.id, name="Vacuum", slug="vacuum", is_active=True)
            db.add_all([locker, product])
            await db.flush()
            cell = LockerCell(
                locker_id=locker.id, label="A2", external_cell_id=EXTERNAL_CELL_ID,
                status=LockerCellStatus.RESERVED, supports_return=True,
            )
            plan = PricePlan(
                product_id=product.id, name="1 day", duration_type="day", duration_value=1,
                base_amount=Decimal("790.00"), currency="RUB", is_active=True,
            )
            db.add_all([cell, plan])
            await db.flush()
            unit = InventoryUnit(
                product_id=product.id, locker_cell_id=cell.id, status=InventoryStatus.RESERVED,
                serial_number="SN-1",
            )
            db.add(unit)
            await db.flush()
            tomorrow = now + timedelta(days=1)
            reservation = Reservation(
                user_id=user.id, product_id=product.id, inventory_unit_id=unit.id,
                locker_id=locker.id, price_plan_id=plan.id, status=ReservationStatus.CONFIRMED,
                duration_type="day", duration_value=1, quoted_amount=Decimal("790.00"),
                preauth_amount=Decimal("790.00"), expires_at=tomorrow, pickup_at=tomorrow,
            )
            db.add(reservation)
            await db.flush()
            payment = Payment(
                user_id=user.id, reservation_id=reservation.id, provider="yookassa",
                provider_payment_id="yk-paid-1", type=PaymentType.PREAUTH,
                status=PaymentStatus.CAPTURED, amount=Decimal("790.00"), currency="RUB",
            )
            rental = Rental(
                user_id=user.id, reservation_id=reservation.id, inventory_unit_id=unit.id,
                pickup_locker_id=locker.id, status=RentalStatus.PICKUP_READY,
                pickup_pin=OLD_PIN, starts_at=tomorrow, planned_end_at=tomorrow + timedelta(days=1),
                pickup_expires_at=tomorrow + timedelta(hours=24),
            )
            session = AuthSession(
                user_id=user.id, refresh_token_hash=uuid4().hex, platform=AuthPlatform.WEB,
                expires_at=now + timedelta(days=1),
            )
            db.add_all([payment, rental, session])
            await db.commit()
            self.ids = {
                "admin": admin.id, "user": user.id, "cell": cell.id, "unit": unit.id,
                "reservation": reservation.id, "payment": payment.id, "rental": rental.id,
                "session": session.id, "locker": locker.id,
            }

        async def fake_get_current_admin(request, db):
            return await db.get(AdminAccount, self.ids["admin"]), None

        self.admin_patch = patch.object(admin_rentals, "get_current_admin", new=fake_get_current_admin)
        self.admin_patch.start()

    async def asyncTearDown(self):
        self.admin_patch.stop()
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

    # ── помощники ───────────────────────────────────────────────

    async def _state(self) -> dict:
        async with SessionLocal() as db:
            rental = await db.get(Rental, self.ids["rental"])
            events = (
                await db.scalars(
                    select(RentalEvent).where(RentalEvent.rental_id == self.ids["rental"])
                )
            ).all()
            return {
                "rental": rental.status,
                "reservation": (await db.get(Reservation, self.ids["reservation"])).status,
                "payment": (await db.get(Payment, self.ids["payment"])).status,
                "unit": (await db.get(InventoryUnit, self.ids["unit"])),
                "cell": (await db.get(LockerCell, self.ids["cell"])).status,
                "pin_events": [e.payload_json for e in events if e.event_type == "pickup_pin_reset"],
            }

    async def _admin_cancel(self):
        async with SessionLocal() as db:
            return await admin_rentals.cancel_rental(str(self.ids["rental"]), _admin_request(), db)

    def _assert_pin_replaced(self, esi_post: AsyncMock) -> None:
        calls = _set_cell_calls(esi_post)
        self.assertEqual(len(calls), 1, calls)
        path, payload = calls[0]
        self.assertEqual(path, f"/set-cell/{SERIAL}/{EXTERNAL_CELL_ID}")
        self.assertEqual(payload["state"], "assigned")
        self.assertNotIn(payload["pin"], (OLD_PIN, "0000", ""))
        # Главное: дверца не открывается.
        self.assertEqual(_opened_cell_paths(esi_post), [])

    # ── оператор ────────────────────────────────────────────────

    async def test_admin_take_back_refunds_keeps_item_and_replaces_pin(self):
        esi_post = AsyncMock(return_value={})
        refund = AsyncMock(return_value={})
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.utils.payment_flow.refund_yookassa_payment", new=refund
        ):
            await self._admin_cancel()

        refund.assert_awaited_once()
        self.assertEqual(refund.await_args.args[0], "yk-paid-1")
        state = await self._state()
        self.assertEqual(state["rental"], RentalStatus.CANCELLED)
        self.assertEqual(state["reservation"], ReservationStatus.CANCELLED)
        self.assertEqual(state["payment"], PaymentStatus.REFUNDED)
        self.assertEqual(state["unit"].status, InventoryStatus.AVAILABLE)
        self.assertEqual(state["unit"].locker_cell_id, self.ids["cell"])
        self.assertEqual(state["cell"], LockerCellStatus.OCCUPIED)
        self._assert_pin_replaced(esi_post)
        self.assertEqual(state["pin_events"], [{"outcome": "replaced"}])

    async def test_admin_cannot_take_back_an_item_on_hands(self):
        async with SessionLocal() as db:
            rental = await db.get(Rental, self.ids["rental"])
            rental.status = RentalStatus.ACTIVE
            unit = await db.get(InventoryUnit, self.ids["unit"])
            unit.status = InventoryStatus.RENTED
            unit.locker_cell_id = None
            await db.commit()

        esi_post = AsyncMock(return_value={})
        refund = AsyncMock(return_value={})
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.utils.payment_flow.refund_yookassa_payment", new=refund
        ):
            with self.assertRaises(HTTPException) as ctx:
                await self._admin_cancel()

        self.assertEqual(ctx.exception.status_code, 409)
        refund.assert_not_awaited()
        esi_post.assert_not_awaited()
        state = await self._state()
        self.assertEqual(state["rental"], RentalStatus.ACTIVE)
        self.assertEqual(state["unit"].status, InventoryStatus.RENTED)
        self.assertEqual(state["payment"], PaymentStatus.CAPTURED)

    async def test_admin_take_back_is_refused_when_money_cannot_be_returned(self):
        esi_post = AsyncMock(return_value={})
        refund = AsyncMock(side_effect=RuntimeError("yookassa is down"))
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.utils.payment_flow.refund_yookassa_payment", new=refund
        ):
            with self.assertRaises(HTTPException) as ctx:
                await self._admin_cancel()

        self.assertEqual(ctx.exception.status_code, 502)
        esi_post.assert_not_awaited()
        state = await self._state()
        self.assertEqual(state["rental"], RentalStatus.PICKUP_READY)
        self.assertEqual(state["payment"], PaymentStatus.CAPTURED)
        self.assertEqual(state["unit"].status, InventoryStatus.RESERVED)

    async def test_locker_failure_does_not_undo_the_cancellation(self):
        esi_post = AsyncMock(side_effect=RuntimeError("locker offline"))
        refund = AsyncMock(return_value={})
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.utils.payment_flow.refund_yookassa_payment", new=refund
        ):
            await self._admin_cancel()

        state = await self._state()
        self.assertEqual(state["rental"], RentalStatus.CANCELLED)
        self.assertEqual(state["payment"], PaymentStatus.REFUNDED)
        self.assertEqual(len(state["pin_events"]), 1)
        self.assertTrue(state["pin_events"][0]["outcome"].startswith("failed:"))

    # ── шедулер: не забрали за 3 часа ───────────────────────────

    async def test_expired_pickup_keeps_cell_occupied_and_replaces_pin(self):
        async with SessionLocal() as db:
            rental = await db.get(Rental, self.ids["rental"])
            rental.pickup_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            await db.commit()

        esi_post = AsyncMock(return_value={})
        refund = AsyncMock(return_value={})
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.utils.payment_flow.refund_yookassa_payment", new=refund
        ):
            await expire_stale_pickup_rentals()

        refund.assert_awaited_once()
        state = await self._state()
        self.assertEqual(state["rental"], RentalStatus.CANCELLED)
        # Раньше тут было VACANT, хотя вещь лежала внутри.
        self.assertEqual(state["cell"], LockerCellStatus.OCCUPIED)
        self.assertEqual(state["unit"].status, InventoryStatus.AVAILABLE)
        self._assert_pin_replaced(esi_post)

    # ── клиент отменяет заранее ─────────────────────────────────

    async def test_client_cancel_before_pickup_replaces_pin(self):
        token = create_access_token(self.ids["user"], self.ids["session"])
        esi_post = AsyncMock(return_value={})
        refund = AsyncMock(return_value={})
        with patch("backend.utils.esi_client._esi_post", new=esi_post), patch(
            "backend.routers.me.refund_yookassa_payment", new=refund
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.post(
                    f"/me/rentals/{self.ids['rental']}/cancel-before-pickup",
                    headers={"Authorization": f"Bearer {token}"},
                )

        self.assertEqual(r.status_code, 200, r.text)
        refund.assert_awaited_once()
        state = await self._state()
        self.assertEqual(state["rental"], RentalStatus.CANCELLED)
        self.assertEqual(state["cell"], LockerCellStatus.OCCUPIED)
        self._assert_pin_replaced(esi_post)

    # ── «ничего не перебивать» ──────────────────────────────────

    async def test_pin_is_left_alone_when_the_cell_already_has_a_new_booking(self):
        """Вещь успели забронировать снова — её новый код не трогаем."""
        async with SessionLocal() as db:
            old = await db.get(Rental, self.ids["rental"])
            old.status = RentalStatus.CANCELLED
            db.add(
                Rental(
                    user_id=self.ids["user"], inventory_unit_id=self.ids["unit"],
                    pickup_locker_id=self.ids["locker"], status=RentalStatus.PICKUP_READY,
                    pickup_pin="7777", planned_end_at=datetime.now(timezone.utc) + timedelta(days=1),
                )
            )
            await db.commit()

        esi_post = AsyncMock(return_value={})
        with patch("backend.utils.esi_client._esi_post", new=esi_post):
            async with SessionLocal() as db:
                rental = await db.get(Rental, self.ids["rental"])
                outcome = await reset_pin_after_pickup_cancel(db, rental)

        self.assertEqual(outcome, "skipped:cell_has_live_rental")
        esi_post.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
