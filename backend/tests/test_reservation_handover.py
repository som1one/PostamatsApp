"""Бронь на будущие даты, пока вещь занята.

Сценарий из жизни: единственная приставка на руках у клиента до конца
дня, календарь показывает завтрашний день свободным, а постамат на
странице товара был «временно недоступен» — забронировать завтра было
нельзя. Теперь бронь принимается, после оплаты ждёт вещь оплаченной, а
аренда с PIN создаётся сама, когда вещь вернулась в ячейку и оператор
подтвердил возврат.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx

# DSN и стабы перекрываем ДО импорта приложения (как в test_full_flow_e2e).
TEST_DB_PATH = os.path.abspath(
    f"./backend/tests/test_reservation_handover_{uuid4().hex}.sqlite"
)
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
os.environ["ESI_DEV_STUB"] = "true"
os.environ["UPLOAD_DEV_STUB"] = "true"

from sqlalchemy import select  # noqa: E402

from backend.main import app  # noqa: E402
from backend.core.database import Base, SessionLocal, engine, get_db  # noqa: E402
from backend.core.settings import settings  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
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
from backend.routers.reservation import _get_available_inventory_unit  # noqa: E402
from backend.utils.products_utils import (  # noqa: E402
    compute_busy_dates_for_product,
    load_available_lockers_for_product,
)
from backend.utils.reservation_auto_confirm import (  # noqa: E402
    auto_confirm_paid_reservations,
)
from backend.utils.reservation_handover import (  # noqa: E402
    NEXT_BOOKING_NOTICE_EVENT,
    get_handover_blocker,
)

MSK = timezone(timedelta(hours=3))


def _utc(value: datetime) -> datetime:
    """SQLite возвращает naive datetime — нормализуем для сравнения."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _msk_midnight(days_ahead: int) -> datetime:
    """Полночь локального дня выдачи — так фронт передаёт startAt."""
    today = datetime.now(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
    return (today + timedelta(days=days_ahead)).astimezone(timezone.utc)


async def _override_get_db():
    async with SessionLocal() as db:
        yield db


class ReservationHandoverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings.YOOKASSA_DEV_STUB = True
        settings.ESI_DEV_STUB = True
        settings.UPLOAD_DEV_STUB = True

        # Другие сьюты подменяют get_db на свою базу — возвращаем общую.
        self._previous_get_db = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = _override_get_db

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        self.city_id = uuid4()
        self.product_id = uuid4()
        self.plan_id = uuid4()
        self.locker_id = uuid4()
        self.cell_id = uuid4()
        self.unit_id = uuid4()
        self.holder_id = uuid4()
        category_id = uuid4()

        async with SessionLocal() as db:
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
                        id=category_id,
                        name="Cat",
                        slug="cat",
                        is_active=True,
                        sort_order=0,
                    ),
                    Product(
                        id=self.product_id,
                        category_id=category_id,
                        name="PS5",
                        slug="ps5",
                        is_active=True,
                    ),
                    PricePlan(
                        id=self.plan_id,
                        product_id=self.product_id,
                        name="1 day",
                        duration_type="day",
                        duration_value=1,
                        base_amount=Decimal("100.00"),
                        currency="RUB",
                        is_active=True,
                    ),
                    LockerLocation(
                        id=self.locker_id,
                        city_id=self.city_id,
                        name="Locker A",
                        address="ул. Тестовая, 1",
                        status=LockerStatus.ONLINE,
                        external_provider="esi",
                        external_locker_id="LOCKER-001",
                    ),
                    LockerCell(
                        id=self.cell_id,
                        locker_id=self.locker_id,
                        label="A1",
                        external_cell_id="A1",
                        status=LockerCellStatus.VACANT,
                        supports_return=True,
                    ),
                    # Клиент, у которого вещь сейчас на руках.
                    User(
                        id=self.holder_id,
                        phone="+79990000001",
                        verification_status=VerificationStatus.APPROVED,
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

    # ── сиды ────────────────────────────────────────────────────

    async def _seed_unit_on_hands(self, *, planned_end_in: timedelta) -> UUID:
        """Вещь забрали из постамата: ячейка пуста, аренда активна."""
        now = datetime.now(timezone.utc)
        rental_id = uuid4()
        async with SessionLocal() as db:
            db.add_all(
                [
                    InventoryUnit(
                        id=self.unit_id,
                        product_id=self.product_id,
                        locker_cell_id=None,
                        status=InventoryStatus.RENTED,
                        serial_number="SN-001",
                    ),
                    Rental(
                        id=rental_id,
                        user_id=self.holder_id,
                        inventory_unit_id=self.unit_id,
                        pickup_locker_id=self.locker_id,
                        status=RentalStatus.ACTIVE,
                        starts_at=now - timedelta(days=1),
                        planned_end_at=now + planned_end_in,
                    ),
                ]
            )
            await db.commit()
        return rental_id

    async def _seed_unit_in_cell(self, status: InventoryStatus) -> None:
        async with SessionLocal() as db:
            cell = await db.get(LockerCell, self.cell_id)
            cell.status = LockerCellStatus.OCCUPIED
            db.add(
                InventoryUnit(
                    id=self.unit_id,
                    product_id=self.product_id,
                    locker_cell_id=self.cell_id,
                    status=status,
                    serial_number="SN-001",
                )
            )
            await db.commit()

    async def _seed_user(self, phone: str) -> UUID:
        user_id = uuid4()
        async with SessionLocal() as db:
            db.add(
                User(
                    id=user_id,
                    phone=phone,
                    verification_status=VerificationStatus.APPROVED,
                )
            )
            await db.commit()
        return user_id

    async def _seed_paid_reservation(
        self,
        *,
        user_id: UUID,
        pickup_at: datetime,
        created_ago: timedelta = timedelta(minutes=10),
    ) -> UUID:
        created_at = datetime.now(timezone.utc) - created_ago
        reservation_id = uuid4()
        async with SessionLocal() as db:
            db.add(
                Reservation(
                    id=reservation_id,
                    user_id=user_id,
                    product_id=self.product_id,
                    inventory_unit_id=self.unit_id,
                    locker_id=self.locker_id,
                    price_plan_id=self.plan_id,
                    status=ReservationStatus.PAYMENT_AUTHORIZED,
                    duration_type="day",
                    duration_value=1,
                    quoted_amount=Decimal("100.00"),
                    preauth_amount=Decimal("100.00"),
                    expires_at=pickup_at + timedelta(hours=24),
                    pickup_at=pickup_at,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            await db.commit()
        return reservation_id

    async def _login_customer(self) -> dict[str, str]:
        r = await self.client.post("/auth/dev-login", json={"phone": "+79991112233"})
        self.assertEqual(r.status_code, 200, r.text)
        login = r.json()["data"]
        async with SessionLocal() as db:
            user = await db.get(User, UUID(login["user"]["id"]))
            user.verification_status = VerificationStatus.APPROVED
            await db.commit()
        self.customer_id = UUID(login["user"]["id"])
        return {"Authorization": f"Bearer {login['accessToken']}"}

    async def _return_unit_to_cell(self, rental_id: UUID) -> None:
        """Клиент вернул вещь: она в ячейке и ждёт проверки оператором."""
        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            rental = await db.get(Rental, rental_id)
            rental.status = RentalStatus.COMPLETED
            rental.actual_end_at = now
            rental.completed_at = now
            unit = await db.get(InventoryUnit, self.unit_id)
            unit.status = InventoryStatus.AWAITING_CONFIRMATION
            unit.locker_cell_id = self.cell_id
            cell = await db.get(LockerCell, self.cell_id)
            cell.status = LockerCellStatus.OCCUPIED
            await db.commit()

    async def _set_unit_status(self, status: InventoryStatus) -> None:
        async with SessionLocal() as db:
            unit = await db.get(InventoryUnit, self.unit_id)
            unit.status = status
            await db.commit()

    async def _age_reservation(self, reservation_id: UUID) -> None:
        """Sweep не трогает бронь первые 90 секунд — состарим её."""
        created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        async with SessionLocal() as db:
            reservation = await db.get(Reservation, reservation_id)
            reservation.created_at = created_at
            await db.commit()

    async def _get_unit(self) -> InventoryUnit:
        async with SessionLocal() as db:
            return await db.get(InventoryUnit, self.unit_id)

    async def _get_reservation(self, reservation_id: UUID) -> Reservation:
        async with SessionLocal() as db:
            return await db.get(Reservation, reservation_id)

    async def _get_rental_for(self, reservation_id: UUID) -> Rental | None:
        async with SessionLocal() as db:
            return (
                await db.scalars(
                    select(Rental).where(Rental.reservation_id == reservation_id)
                )
            ).first()

    # ── тесты ───────────────────────────────────────────────────

    async def test_booking_ahead_while_unit_is_on_hands(self):
        """Весь путь: занято → бронь → ожидание → возврат → проверка → PIN."""
        holder_rental_id = await self._seed_unit_on_hands(planned_end_in=timedelta(hours=2))
        auth = await self._login_customer()
        today = _msk_midnight(0)
        pickup_at = _msk_midnight(2)

        # Страница товара: свободных нет, но постамат выбирается.
        r = await self.client.get(
            f"/products/{self.product_id}", params={"cityId": str(self.city_id)}
        )
        self.assertEqual(r.status_code, 200, r.text)
        lockers = r.json()["data"]["product"]["availableLockers"]
        self.assertEqual(len(lockers), 1)
        self.assertEqual(lockers[0]["lockerId"], str(self.locker_id))
        self.assertEqual(lockers[0]["availableUnits"], 0)
        self.assertEqual(lockers[0]["bookableUnits"], 1)

        # Календарь: сегодня занято, день выдачи свободен.
        r = await self.client.get(
            f"/products/{self.product_id}/busy-dates",
            params={"lockerId": str(self.locker_id)},
        )
        self.assertEqual(r.status_code, 200, r.text)
        busy = r.json()["data"]["busyDates"]
        self.assertIn(today.astimezone(MSK).date().isoformat(), busy)
        self.assertNotIn(pickup_at.astimezone(MSK).date().isoformat(), busy)

        r = await self.client.get(
            f"/products/{self.product_id}/pricing",
            params={
                "lockerId": str(self.locker_id),
                "durationType": "day",
                "durationValue": 1,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)

        booking = {
            "productId": str(self.product_id),
            "lockerId": str(self.locker_id),
            "durationType": "day",
            "durationValue": 1,
        }

        # На сегодня вещь не забронировать — она ещё у клиента.
        r = await self.client.post(
            "/reservations", headers=auth, json={**booking, "startAt": today.isoformat()}
        )
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], "PRODUCT_NOT_AVAILABLE")

        r = await self.client.post(
            "/reservations", headers=auth, json={**booking, "startAt": pickup_at.isoformat()}
        )
        self.assertEqual(r.status_code, 200, r.text)
        reservation_id = UUID(r.json()["data"]["reservation"]["id"])
        # Бронь не должна «освободить» или «зарезервировать» вещь на руках.
        self.assertEqual((await self._get_unit()).status, InventoryStatus.RENTED)

        r = await self.client.post(
            "/payments/preauth", headers=auth, json={"reservationId": str(reservation_id)}
        )
        self.assertEqual(r.status_code, 200, r.text)
        payment_id = r.json()["data"]["payment"]["id"]
        r = await self.client.post(
            f"/payments/{payment_id}/authorize-dev-stub", headers=auth
        )
        self.assertEqual(r.status_code, 200, r.text)

        # Confirm после оплаты: PIN выдавать некуда — бронь ждёт.
        with patch("backend.utils.sms_ru.send_sms", new=AsyncMock()) as send_sms:
            r = await self.client.post(
                f"/reservations/{reservation_id}/confirm",
                headers=auth,
                json={"paymentId": payment_id},
            )
            self.assertEqual(r.status_code, 200, r.text)
            data = r.json()["data"]
            self.assertIsNone(data["rental"])
            self.assertEqual(data["handover"], {"status": "waiting", "reason": "unit_out"})
            self.assertEqual(data["reservation"]["status"], "payment_authorized")

            # Тому, у кого вещь на руках, ушло одно напоминание — и только одно,
            # сколько бы раз клиент ни обновлял страницу оплаты.
            r = await self.client.post(
                f"/reservations/{reservation_id}/confirm",
                headers=auth,
                json={"paymentId": payment_id},
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(send_sms.await_count, 1)
            self.assertEqual(send_sms.await_args.args[0], "+79990000001")

        async with SessionLocal() as db:
            notices = (
                await db.scalars(
                    select(RentalEvent).where(
                        RentalEvent.rental_id == holder_rental_id,
                        RentalEvent.event_type == NEXT_BOOKING_NOTICE_EVENT,
                    )
                )
            ).all()
        self.assertEqual(len(notices), 1)

        reservation = await self._get_reservation(reservation_id)
        self.assertEqual(reservation.status, ReservationStatus.PAYMENT_AUTHORIZED)
        # Ждать можно до конца дня выдачи, а не два часа окна оплаты.
        self.assertEqual(_utc(reservation.expires_at), pickup_at + timedelta(hours=24))
        self.assertIsNone(await self._get_rental_for(reservation_id))

        r = await self.client.get("/me/reservations", headers=auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["data"]["reservations"][0]["waitingForUnit"])

        # Вещь всё ещё на руках — sweep ничего не выдаёт.
        await self._age_reservation(reservation_id)
        await auto_confirm_paid_reservations()
        self.assertIsNone(await self._get_rental_for(reservation_id))

        # Вернули, но оператор ещё не проверил — рано.
        await self._return_unit_to_cell(holder_rental_id)
        await auto_confirm_paid_reservations()
        self.assertIsNone(await self._get_rental_for(reservation_id))

        # Оператор подтвердил возврат — следующий тик выдаёт PIN.
        await self._set_unit_status(InventoryStatus.AVAILABLE)
        await auto_confirm_paid_reservations()

        rental = await self._get_rental_for(reservation_id)
        self.assertIsNotNone(rental)
        self.assertEqual(rental.status, RentalStatus.PICKUP_READY)
        self.assertEqual(rental.user_id, self.customer_id)
        self.assertEqual(len(rental.pickup_pin), 4)
        self.assertEqual(_utc(rental.starts_at), pickup_at)
        self.assertEqual(_utc(rental.pickup_expires_at), pickup_at + timedelta(hours=24))
        self.assertEqual(
            (await self._get_reservation(reservation_id)).status,
            ReservationStatus.CONFIRMED,
        )
        self.assertEqual((await self._get_unit()).status, InventoryStatus.RESERVED)

    async def test_cancelling_booking_keeps_unit_on_hands(self):
        """Отмена брони не должна превращать вещь на руках в «свободную»."""
        await self._seed_unit_on_hands(planned_end_in=timedelta(hours=2))
        auth = await self._login_customer()

        r = await self.client.post(
            "/reservations",
            headers=auth,
            json={
                "productId": str(self.product_id),
                "lockerId": str(self.locker_id),
                "durationType": "day",
                "durationValue": 1,
                "startAt": _msk_midnight(2).isoformat(),
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        reservation_id = r.json()["data"]["reservation"]["id"]

        r = await self.client.post(f"/me/reservations/{reservation_id}/cancel", headers=auth)
        self.assertEqual(r.status_code, 200, r.text)

        unit = await self._get_unit()
        self.assertEqual(unit.status, InventoryStatus.RENTED)
        self.assertIsNone(unit.locker_cell_id)

    async def test_earlier_booking_gets_the_unit_first(self):
        """Две оплаченные брони на одну вещь: PIN получает та, что раньше."""
        await self._seed_unit_in_cell(InventoryStatus.AVAILABLE)
        later_user = await self._seed_user("+79990000002")
        earlier_user = await self._seed_user("+79990000003")
        # Позднюю бронь создаём первой — порядок создания решать не должен.
        later = await self._seed_paid_reservation(
            user_id=later_user,
            pickup_at=_msk_midnight(5),
            created_ago=timedelta(minutes=30),
        )
        earlier = await self._seed_paid_reservation(
            user_id=earlier_user,
            pickup_at=_msk_midnight(2),
            created_ago=timedelta(minutes=10),
        )

        await auto_confirm_paid_reservations()

        self.assertIsNotNone(await self._get_rental_for(earlier))
        self.assertIsNone(await self._get_rental_for(later))
        self.assertEqual(
            (await self._get_reservation(later)).status,
            ReservationStatus.PAYMENT_AUTHORIZED,
        )

        # Пока первая аренда не закрыта, вторая ждёт — двух незавершённых
        # аренд на одну вещь быть не должно.
        await auto_confirm_paid_reservations()
        self.assertIsNone(await self._get_rental_for(later))
        async with SessionLocal() as db:
            unit = await db.get(InventoryUnit, self.unit_id)
            reservation = await db.get(Reservation, later)
            blocker = await get_handover_blocker(
                db, reservation, unit, now=datetime.now(timezone.utc)
            )
        self.assertEqual(blocker, "unit_held")

    async def test_unit_held_for_pickup_blocks_earlier_dates(self):
        """Вещь отложена под выдачу через 5 дней — раньше её не забронировать."""
        await self._seed_unit_in_cell(InventoryStatus.RESERVED)
        starts_at = _msk_midnight(5)
        async with SessionLocal() as db:
            db.add(
                Rental(
                    id=uuid4(),
                    user_id=self.holder_id,
                    inventory_unit_id=self.unit_id,
                    pickup_locker_id=self.locker_id,
                    pickup_pin="1234",
                    status=RentalStatus.PICKUP_READY,
                    starts_at=starts_at,
                    pickup_expires_at=starts_at + timedelta(hours=24),
                    planned_end_at=starts_at + timedelta(days=1),
                )
            )
            await db.commit()

        async with SessionLocal() as db:
            before = await _get_available_inventory_unit(
                self.locker_id,
                self.product_id,
                db,
                desired_start=_msk_midnight(2),
                desired_end=_msk_midnight(3),
            )
            after = await _get_available_inventory_unit(
                self.locker_id,
                self.product_id,
                db,
                desired_start=_msk_midnight(6),
                desired_end=_msk_midnight(7),
            )
            busy = await compute_busy_dates_for_product(
                db, self.product_id, locker_id=self.locker_id
            )
            lockers = await load_available_lockers_for_product(
                db, self.product_id, self.city_id
            )

        self.assertIsNone(before)
        self.assertIsNotNone(after)
        # Календарь обязан говорить то же самое, что и проверка при брони.
        for days_ahead in range(0, 6):
            self.assertIn(
                _msk_midnight(days_ahead).astimezone(MSK).date().isoformat(), busy
            )
        self.assertNotIn(_msk_midnight(7).astimezone(MSK).date().isoformat(), busy)
        self.assertEqual(lockers[0]["availableUnits"], 0)
        self.assertEqual(lockers[0]["bookableUnits"], 1)

    async def test_unit_back_on_pickup_day_keeps_the_whole_day(self):
        """Вещь освободилась уже в день выдачи — у клиента остаётся весь день."""
        await self._seed_unit_in_cell(InventoryStatus.AVAILABLE)
        customer = await self._seed_user("+79990000002")
        pickup_at = _msk_midnight(0)
        now = datetime.now(timezone.utc)
        reservation_id = await self._seed_paid_reservation(
            user_id=customer,
            pickup_at=pickup_at,
            created_ago=timedelta(days=2),
        )
        # Предыдущий клиент вернул вещь уже после того, как её забронировали.
        async with SessionLocal() as db:
            db.add(
                Rental(
                    id=uuid4(),
                    user_id=self.holder_id,
                    inventory_unit_id=self.unit_id,
                    pickup_locker_id=self.locker_id,
                    status=RentalStatus.COMPLETED,
                    starts_at=now - timedelta(days=3),
                    planned_end_at=now - timedelta(days=1),
                    actual_end_at=now - timedelta(minutes=30),
                    completed_at=now - timedelta(minutes=30),
                )
            )
            await db.commit()

        await auto_confirm_paid_reservations()

        rental = await self._get_rental_for(reservation_id)
        self.assertIsNotNone(rental)
        deadline = _utc(rental.pickup_expires_at)
        self.assertGreaterEqual(deadline, pickup_at + timedelta(hours=24))
        self.assertGreaterEqual(deadline, now + timedelta(hours=3) - timedelta(minutes=1))

    async def test_stale_rental_does_not_block_a_free_unit(self):
        """Мусорная незакрытая аренда не мешает брать вещь, которая в ячейке."""
        await self._seed_unit_in_cell(InventoryStatus.AVAILABLE)
        customer = await self._seed_user("+79990000002")
        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            db.add(
                Rental(
                    id=uuid4(),
                    user_id=self.holder_id,
                    inventory_unit_id=self.unit_id,
                    pickup_locker_id=self.locker_id,
                    status=RentalStatus.ACTIVE,
                    starts_at=now - timedelta(days=30),
                    planned_end_at=now - timedelta(days=29),
                )
            )
            await db.commit()
        reservation_id = await self._seed_paid_reservation(
            user_id=customer, pickup_at=_msk_midnight(0)
        )

        async with SessionLocal() as db:
            unit = await _get_available_inventory_unit(
                self.locker_id,
                self.product_id,
                db,
                # Свою же бронь при подборе вещи не учитываем.
                source_reservation=await db.get(Reservation, reservation_id),
                desired_start=_msk_midnight(0),
                desired_end=_msk_midnight(1),
            )
        self.assertIsNotNone(unit)

        await auto_confirm_paid_reservations()
        self.assertIsNotNone(await self._get_rental_for(reservation_id))

    async def test_paid_reservation_is_not_expired_by_confirm(self):
        """Оплаченную бронь закрывает шедулер с возвратом денег, не confirm."""
        await self._seed_unit_on_hands(planned_end_in=timedelta(hours=2))
        auth = await self._login_customer()
        reservation_id = await self._seed_paid_reservation(
            user_id=self.customer_id, pickup_at=_msk_midnight(-2)
        )

        r = await self.client.post(
            f"/reservations/{reservation_id}/confirm", headers=auth, json={}
        )
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], "RESERVATION_EXPIRED")
        self.assertEqual(
            (await self._get_reservation(reservation_id)).status,
            ReservationStatus.PAYMENT_AUTHORIZED,
        )


if __name__ == "__main__":
    unittest.main()
