"""Цена и бронь на срок, под который у товара нет готового тарифа.

Сценарий из жизни: у PS5 заведён только тариф «1 день» за 899 ₽. Клиент
выбрал в календаре 9 суток, а витрина подставила ближайший тариф снизу —
показала «Итого 899 ₽» и оформила бы аренду на одни сутки. У караоке с
тарифами 1/2/3/7 дней за 18 выбранных суток выходила цена семи.

Теперь срок без своего тарифа считается от суточного по шкале из-под
календаря, а готовый тариф на тот же срок остаётся главнее шкалы.

Поверх — цена по дням недели: у товаров с галочкой каждые сутки аренды
дорожают на наценку своего дня (владелец поднимает цену на выходные).
"""

from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException, Request

# DSN и стабы перекрываем ДО импорта приложения (как в test_full_flow_e2e).
TEST_DB_PATH = os.path.abspath(
    f"./backend/tests/test_rental_pricing_{uuid4().hex}.sqlite"
)
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
os.environ["ESI_DEV_STUB"] = "true"
os.environ["UPLOAD_DEV_STUB"] = "true"

from backend.main import app  # noqa: E402
from backend.core.database import Base, SessionLocal, engine, get_db  # noqa: E402
from backend.core.settings import settings  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.admin_account import AdminAccount  # noqa: E402
from backend.models.enums import AdminRole  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.models.weekday_price_markup import WeekdayPriceMarkup  # noqa: E402
from backend.routers.admin import weekday_pricing as admin_weekday_pricing  # noqa: E402
from backend.schemas.admin_panel_schemas import AdminWeekdayMarkupsPayload  # noqa: E402
from backend.utils.admin_auth_utils import hash_password  # noqa: E402
from backend.utils.rental_extension import resolve_extension_price  # noqa: E402
from backend.utils.rental_pricing import (  # noqa: E402
    MAX_PROGRESSIVE_DAYS,
    progressive_discount_percent,
    progressive_total_minor,
    rental_start_day,
    weekday_markup_total_minor,
)

# Наценка владельца из переписки: пятница, суббота и воскресенье дороже.
WEEKEND_MARKUPS = (0, 0, 0, 0, 20, 20, 20)
MSK = timezone(timedelta(hours=3))


def _next_weekday(weekday: int) -> date:
    """Ближайший будущий день недели (0 — пн): бронь в прошлом не нужна."""
    tomorrow = datetime.now(MSK).date() + timedelta(days=1)
    return tomorrow + timedelta(days=(weekday - tomorrow.weekday()) % 7)


def _msk_midnight_utc(day: date) -> str:
    """Как сайт шлёт startAt: полночь выбранной даты, переведённая в UTC."""
    moment = datetime(day.year, day.month, day.day, tzinfo=MSK)
    return moment.astimezone(timezone.utc).isoformat()


def _make_admin_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "headers": [(b"user-agent", b"pytest")],
            "path": "/api/admin/weekday-pricing",
            "client": ("127.0.0.1", 0),
        }
    )


class ProgressiveScaleTests(unittest.TestCase):
    def test_discount_follows_the_scale_under_the_calendar(self):
        expected = {1: 0, 2: 5, 3: 10, 4: 11, 5: 12, 7: 14, 9: 16, 14: 21}
        for days, percent in expected.items():
            self.assertEqual(progressive_discount_percent(days), percent, days)

    def test_discount_is_capped(self):
        self.assertEqual(progressive_discount_percent(17), 24)
        self.assertEqual(progressive_discount_percent(18), 25)
        self.assertEqual(progressive_discount_percent(30), 25)

    def test_total_matches_ready_made_plans_in_the_bundle(self):
        # Караоке: 590 ₽/сутки, тарифы в бандле каталога — 1120 / 1590 / 3550.
        self.assertEqual(progressive_total_minor(59000, 1), 59000)
        self.assertEqual(progressive_total_minor(59000, 2), 112000)
        self.assertEqual(progressive_total_minor(59000, 3), 159000)
        self.assertEqual(progressive_total_minor(59000, 7), 355000)
        # Puzzi: 1250 ₽/сутки, 3 дня = 3375 → 3380 (половина вверх).
        self.assertEqual(progressive_total_minor(125000, 3), 338000)

    def test_total_for_terms_from_the_bug_report(self):
        self.assertEqual(progressive_total_minor(89900, 9), 680000)
        # 590 × 18 × 0,75 = 7965 → 7970 (половина вверх).
        self.assertEqual(progressive_total_minor(59000, 18), 797000)

    def test_total_is_zero_without_a_price_or_a_term(self):
        self.assertEqual(progressive_total_minor(0, 5), 0)
        self.assertEqual(progressive_total_minor(59000, 0), 0)


class WeekdayMarkupTests(unittest.TestCase):
    FRIDAY = date(2026, 10, 23)
    SATURDAY = date(2026, 10, 24)
    MONDAY = date(2026, 10, 26)

    def test_each_day_of_the_term_gets_its_own_markup(self):
        # Сутки в субботу: 590 × 1,2 = 708 → 710.
        self.assertEqual(
            weekday_markup_total_minor(59000, self.SATURDAY, 1, WEEKEND_MARKUPS), 71000
        )
        # Будний день — без наценки.
        self.assertEqual(
            weekday_markup_total_minor(59000, self.MONDAY, 1, WEEKEND_MARKUPS), 59000
        )
        # Пт–вс целиком в выходных: готовый тариф 3 дня 1590 × 1,2 = 1908 → 1910.
        self.assertEqual(
            weekday_markup_total_minor(159000, self.FRIDAY, 3, WEEKEND_MARKUPS), 191000
        )
        # Неделя с понедельника: три дня из семи по +20% → 3550 × 760/700.
        self.assertEqual(
            weekday_markup_total_minor(355000, self.MONDAY, 7, WEEKEND_MARKUPS), 385000
        )

    def test_negative_markup_is_a_discount(self):
        markups = (-10, 0, 0, 0, 0, 0, 0)
        self.assertEqual(weekday_markup_total_minor(59000, self.MONDAY, 1, markups), 53000)

    def test_price_without_markup_is_not_rounded_again(self):
        # Тариф из product_filter может быть не кратен 10 ₽ — без наценки он
        # должен остаться ровно тем же.
        self.assertEqual(
            weekday_markup_total_minor(59900, self.MONDAY, 3, WEEKEND_MARKUPS), 59900
        )

    def test_start_day_is_the_date_picked_in_the_calendar(self):
        # Полночь субботы по Москве.
        self.assertEqual(
            rental_start_day(datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc)),
            self.SATURDAY,
        )
        # Полночь субботы в Екатеринбурге — 22:00 пятницы по Москве.
        self.assertEqual(
            rental_start_day(datetime(2026, 10, 23, 19, 0, tzinfo=timezone.utc)),
            self.SATURDAY,
        )
        # Полночь субботы в Калининграде — 01:00 субботы по Москве.
        self.assertEqual(
            rental_start_day(datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)),
            self.SATURDAY,
        )

    def test_start_day_without_a_date_is_today_in_moscow(self):
        # 01:30 субботы по Москве — уже суббота, хотя в UTC ещё пятница.
        now = datetime(2026, 10, 23, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(rental_start_day(None, now), self.SATURDAY)


async def _override_get_db():
    async with SessionLocal() as db:
        yield db


class RentalPricingApiTests(unittest.IsolatedAsyncioTestCase):
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
        self.category_id = uuid4()
        self.locker_id = uuid4()
        self.ps5_id = uuid4()
        self.ps5_day_plan_id = uuid4()
        self.karaoke_id = uuid4()

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
                        id=self.category_id,
                        name="Cat",
                        slug="cat",
                        is_active=True,
                        sort_order=0,
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
                ]
            )
            await db.commit()

        # Как на проде: у PS5 один суточный тариф, у караоке — 1/2/3/7 дней.
        # Недельный тариф караоке нарочно не совпадает со шкалой (3550).
        await self._seed_product(
            self.ps5_id, "ps5", {1: "899.00"}, plan_ids={1: self.ps5_day_plan_id}
        )
        await self._seed_product(
            self.karaoke_id,
            "karaoke",
            {1: "590.00", 2: "1120.00", 3: "1590.00", 7: "3500.00"},
        )

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

    async def _seed_product(
        self,
        product_id: UUID,
        slug: str,
        plans: dict[int, str],
        *,
        plan_ids: dict[int, UUID] | None = None,
    ) -> None:
        """Товар с суточными тарифами и одной единицей в ячейке постамата."""
        cell_id = uuid4()
        async with SessionLocal() as db:
            db.add_all(
                [
                    Product(
                        id=product_id,
                        category_id=self.category_id,
                        name=slug,
                        slug=slug,
                        is_active=True,
                    ),
                    LockerCell(
                        id=cell_id,
                        locker_id=self.locker_id,
                        label=slug,
                        external_cell_id=slug,
                        status=LockerCellStatus.OCCUPIED,
                        supports_return=True,
                    ),
                    InventoryUnit(
                        id=uuid4(),
                        product_id=product_id,
                        locker_cell_id=cell_id,
                        status=InventoryStatus.AVAILABLE,
                        serial_number=f"SN-{slug}",
                    ),
                ]
            )
            for days, amount in plans.items():
                db.add(
                    PricePlan(
                        id=(plan_ids or {}).get(days, uuid4()),
                        product_id=product_id,
                        name=f"{days} d",
                        duration_type="day",
                        duration_value=days,
                        base_amount=Decimal(amount),
                        currency="RUB",
                        is_active=True,
                    )
                )
            await db.commit()

    async def _login_customer(self) -> dict[str, str]:
        r = await self.client.post("/auth/dev-login", json={"phone": "+79991112233"})
        self.assertEqual(r.status_code, 200, r.text)
        login = r.json()["data"]
        async with SessionLocal() as db:
            user = await db.get(User, UUID(login["user"]["id"]))
            user.verification_status = VerificationStatus.APPROVED
            await db.commit()
        return {"Authorization": f"Bearer {login['accessToken']}"}

    async def _pricing(
        self,
        product_id: UUID,
        days: int,
        duration_type: str = "day",
        start_date: date | str | None = None,
    ) -> httpx.Response:
        params = {
            "lockerId": str(self.locker_id),
            "durationType": duration_type,
            "durationValue": days,
        }
        if start_date is not None:
            params["startDate"] = str(start_date)
        return await self.client.get(f"/products/{product_id}/pricing", params=params)

    async def _enable_weekday_pricing(
        self, product_id: UUID, markups: tuple[int, ...] = WEEKEND_MARKUPS
    ) -> None:
        async with SessionLocal() as db:
            product = await db.get(Product, product_id)
            product.weekday_pricing_enabled = True
            for weekday, percent in enumerate(markups):
                await db.merge(WeekdayPriceMarkup(weekday=weekday, percent=percent))
            await db.commit()

    # ── тесты ───────────────────────────────────────────────────

    async def test_term_without_a_plan_is_priced_by_the_scale(self):
        """PS5 на 9 суток — не цена одних суток, а 899 × 9 со скидкой 16%."""
        r = await self._pricing(self.ps5_id, 9)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()["data"]
        self.assertEqual(data["durationValue"], 9)
        self.assertEqual(data["totalAmount"], 680000)
        self.assertEqual(data["preauthAmount"], 680000)

        # Суточный тариф при этом не тронут.
        r = await self._pricing(self.ps5_id, 1)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["totalAmount"], 89900)

    async def test_ready_made_plan_beats_the_scale(self):
        """Караоке: 7 дней — готовый тариф, 18 суток — уже шкала, а не цена семи."""
        r = await self._pricing(self.karaoke_id, 7)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["totalAmount"], 350000)

        r = await self._pricing(self.karaoke_id, 18)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["totalAmount"], 797000)

    async def test_scale_does_not_reach_past_the_calendar(self):
        r = await self._pricing(self.ps5_id, MAX_PROGRESSIVE_DAYS)
        self.assertEqual(r.status_code, 200, r.text)

        r = await self._pricing(self.ps5_id, MAX_PROGRESSIVE_DAYS + 1)
        self.assertEqual(r.status_code, 404, r.text)
        self.assertEqual(r.json()["detail"], "PRICE_PLAN_NOT_FOUND")

        # Шкала — только про сутки: часового тарифа у товара нет.
        r = await self._pricing(self.ps5_id, 3, duration_type="hour")
        self.assertEqual(r.status_code, 404, r.text)

    async def test_no_daily_plan_means_no_scale(self):
        weekly_only_id = uuid4()
        await self._seed_product(weekly_only_id, "weekly-only", {7: "3000.00"})

        r = await self._pricing(weekly_only_id, 7)
        self.assertEqual(r.status_code, 200, r.text)
        r = await self._pricing(weekly_only_id, 9)
        self.assertEqual(r.status_code, 404, r.text)
        self.assertEqual(r.json()["detail"], "PRICE_PLAN_NOT_FOUND")

    async def test_reservation_is_made_for_the_chosen_term(self):
        """Бронь на 9 суток: срок и сумма — за 9 суток, а не за тариф «1 день»."""
        auth = await self._login_customer()
        booking = {
            "productId": str(self.ps5_id),
            "lockerId": str(self.locker_id),
            "durationType": "day",
            "durationValue": 9,
        }

        r = await self.client.post("/reservations/quote", headers=auth, json=booking)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["quote"]["quotedAmount"], 680000)

        r = await self.client.post("/reservations", headers=auth, json=booking)
        self.assertEqual(r.status_code, 200, r.text)
        created = r.json()["data"]["reservation"]
        self.assertEqual(created["durationValue"], 9)
        self.assertEqual(created["quotedAmount"], 680000)
        self.assertEqual(created["preauthAmount"], 680000)

        async with SessionLocal() as db:
            reservation = await db.get(Reservation, UUID(created["id"]))
        self.assertEqual(reservation.duration_value, 9)
        self.assertEqual(reservation.quoted_amount, Decimal("6800.00"))
        self.assertEqual(reservation.preauth_amount, Decimal("6800.00"))
        # Строки тарифа на 9 суток нет — бронь ссылается на суточный,
        # от которого посчитана сумма.
        self.assertEqual(reservation.price_plan_id, self.ps5_day_plan_id)

        # Страница брони отдаёт ту же сумму, что ушла в предавторизацию.
        r = await self.client.get(f"/reservations/{created['id']}", headers=auth)
        self.assertEqual(r.status_code, 200, r.text)
        fetched = r.json()["data"]["reservation"]
        self.assertEqual(fetched["durationValue"], 9)
        self.assertEqual(fetched["pricing"]["quotedAmount"], 680000)

    # ── цена по дням недели ─────────────────────────────────────

    async def test_weekend_day_costs_more_for_a_product_with_the_checkbox(self):
        await self._enable_weekday_pricing(self.karaoke_id)
        saturday = _next_weekday(5)

        r = await self._pricing(self.karaoke_id, 1, start_date=saturday)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()["data"]
        self.assertEqual(data["totalAmount"], 71000)
        self.assertEqual(data["preauthAmount"], 71000)
        self.assertEqual(data["startDate"], saturday.isoformat())

        r = await self._pricing(self.karaoke_id, 1, start_date=_next_weekday(0))
        self.assertEqual(r.json()["data"]["totalAmount"], 59000)

        # Готовый тариф на 3 дня с пятницы — все три дня с наценкой.
        r = await self._pricing(self.karaoke_id, 3, start_date=_next_weekday(4))
        self.assertEqual(r.json()["data"]["totalAmount"], 191000)

    async def test_product_without_the_checkbox_ignores_markups(self):
        await self._enable_weekday_pricing(self.karaoke_id)

        r = await self._pricing(self.ps5_id, 9, start_date=_next_weekday(4))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["totalAmount"], 680000)

    async def test_product_page_gets_markups_only_with_the_checkbox(self):
        await self._enable_weekday_pricing(self.karaoke_id)

        r = await self.client.get(f"/products/{self.karaoke_id}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            r.json()["data"]["product"]["weekdayMarkups"], list(WEEKEND_MARKUPS)
        )

        r = await self.client.get(f"/products/{self.ps5_id}")
        self.assertIsNone(r.json()["data"]["product"]["weekdayMarkups"])

    async def test_pricing_rejects_a_malformed_start_date(self):
        r = await self._pricing(self.karaoke_id, 1, start_date="24.10.2026")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["detail"], "INVALID_START_DATE")

    async def test_reservation_charges_the_markup_of_the_pickup_day(self):
        await self._enable_weekday_pricing(self.karaoke_id)
        auth = await self._login_customer()
        booking = {
            "productId": str(self.karaoke_id),
            "lockerId": str(self.locker_id),
            "durationType": "day",
            "durationValue": 1,
            "startAt": _msk_midnight_utc(_next_weekday(5)),
        }

        r = await self.client.post("/reservations/quote", headers=auth, json=booking)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["quote"]["quotedAmount"], 71000)

        r = await self.client.post("/reservations", headers=auth, json=booking)
        self.assertEqual(r.status_code, 200, r.text)
        created = r.json()["data"]["reservation"]
        self.assertEqual(created["quotedAmount"], 71000)
        self.assertEqual(created["preauthAmount"], 71000)

        async with SessionLocal() as db:
            reservation = await db.get(Reservation, UUID(created["id"]))
        self.assertEqual(reservation.quoted_amount, Decimal("710.00"))

    async def test_extension_days_get_the_markup_too(self):
        """Иначе выходные выгоднее добирать продлением будней аренды."""
        await self._enable_weekday_pricing(self.karaoke_id)
        saturday = datetime.fromisoformat(_msk_midnight_utc(_next_weekday(5)))
        monday = datetime.fromisoformat(_msk_midnight_utc(_next_weekday(0)))

        async with SessionLocal() as db:
            _, amount, _ = await resolve_extension_price(
                db, self.karaoke_id, "day", 1, starts_at=saturday
            )
            self.assertEqual(amount, 71000)
            _, amount, _ = await resolve_extension_price(
                db, self.karaoke_id, "day", 1, starts_at=monday
            )
            self.assertEqual(amount, 59000)

    async def test_admin_saves_markups_within_limits(self):
        await self._enable_weekday_pricing(self.karaoke_id, (0,) * 7)
        async with SessionLocal() as db:
            admin = AdminAccount(
                id=uuid4(),
                name="Root",
                login="root",
                role=AdminRole.SUPER_ADMIN,
                password_hash=hash_password("irrelevant-for-this-test"),
            )
            db.add(admin)
            await db.commit()
            admin_id = admin.id

        async def fake_get_current_admin(request, db):
            return await db.get(AdminAccount, admin_id), None

        original = admin_weekday_pricing.get_current_admin
        admin_weekday_pricing.get_current_admin = fake_get_current_admin
        try:
            async with SessionLocal() as db:
                payload = await admin_weekday_pricing.update_weekday_pricing(
                    _make_admin_request(),
                    AdminWeekdayMarkupsPayload(markups=[0, 0, 0, 0, 10, 25, 25]),
                    db,
                )
            self.assertEqual(payload["data"]["markups"], [0, 0, 0, 0, 10, 25, 25])
            self.assertEqual(payload["data"]["enabledProductCount"], 1)

            async with SessionLocal() as db:
                with self.assertRaises(HTTPException) as ctx:
                    await admin_weekday_pricing.update_weekday_pricing(
                        _make_admin_request(),
                        AdminWeekdayMarkupsPayload(markups=[0, 0, 0, 0, 0, -100, 0]),
                        db,
                    )
            self.assertEqual(ctx.exception.status_code, 422)
        finally:
            admin_weekday_pricing.get_current_admin = original

        # Отклонённое сохранение ничего не поменяло, а сохранённое — уже в цене:
        # 590 × 1,25 = 737,5 → 740.
        r = await self._pricing(self.karaoke_id, 1, start_date=_next_weekday(5))
        self.assertEqual(r.json()["data"]["totalAmount"], 74000)


if __name__ == "__main__":
    unittest.main()
