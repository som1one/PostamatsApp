"""Франшиза видит только свой город.

Проверяем три вещи:

1. Списочные ручки (пользователи, аренды, постаматы, города, верификация,
   дашборд) режутся по ``admin_accounts.city_id``.
2. Закрытые разделы (каталог, обратная связь, аудит) и чужие объекты отдают 403.
3. Управление франшизами: выдача доступа, выключение, смена пароля,
   статистика и адресация уведомлений по городу — в обоих каналах
   (Telegram и MAX).
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.models.admin_account import AdminAccount
from backend.models.admin_account_city import admin_account_cities
from backend.models.admin_audit_event import AdminAuditEvent
from backend.models.admin_auth_session import AdminAuthSession
from backend.models.city import City
from backend.models.enums import (
    AdminRole,
    DocumentType,
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    RentalStatus,
    VerificationStatus,
)
from backend.models.inventory_movement import InventoryMovement
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.max_admin_subscriber import MaxAdminSubscriber
from backend.models.payment import Payment
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.rental import Rental
from backend.models.reservation import Reservation
from backend.models.telegram_admin_subscriber import TelegramAdminSubscriber
from backend.models.user import User
from backend.models.verification_request import VerificationRequest
from backend.routers.admin import auth as admin_auth_router
from backend.routers.admin import cities as admin_cities_router
from backend.routers.admin import franchises as franchises_router
from backend.routers.admin import lockers as admin_lockers_router
from backend.routers.admin import rentals as admin_rentals_router
from backend.routers.admin import users as admin_users_router
from backend.routers.admin import verification_queue as admin_verification_router
from backend.schemas.admin_auth_schemas import AdminLoginPayload
from backend.schemas.admin_franchise_schemas import (
    AdminCreateFranchisePayload,
    AdminFranchisePasswordPayload,
    AdminUpdateFranchisePayload,
)
from backend.schemas.admin_panel_schemas import AdminCreateCityPayload
from backend.utils.admin_auth_utils import hash_password, verify_password
from backend.utils.admin_scope import (
    ensure_rental_in_scope,
    franchise_city_ids,
    require_not_franchise,
    require_super_admin,
)
from backend.utils.max_admin_subscribers import get_active_recipients
from backend.utils.telegram_admin_subscribers import get_active_chat_ids

TEST_DB_URL = "sqlite+aiosqlite:///test_admin_franchise_scope.sqlite"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)

TEST_TABLES = [
    City.__table__,
    admin_account_cities,
    ProductCategory.__table__,
    Product.__table__,
    AdminAccount.__table__,
    AdminAuthSession.__table__,
    AdminAuditEvent.__table__,
    LockerLocation.__table__,
    LockerCell.__table__,
    InventoryUnit.__table__,
    InventoryMovement.__table__,
    User.__table__,
    VerificationRequest.__table__,
    PricePlan.__table__,
    Reservation.__table__,
    Rental.__table__,
    Payment.__table__,
    TelegramAdminSubscriber.__table__,
    MaxAdminSubscriber.__table__,
]


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"user-agent", b"pytest")],
        "path": "/api/admin/franchises",
        "client": ("127.0.0.1", 0),
    }
    return Request(scope)


class AdminFranchiseScopeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with test_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=TEST_TABLES)
            )

        now = datetime.now(timezone.utc)
        async with TestSessionLocal() as db:
            city_a = City(
                id=uuid4(), name="Питер", slug="spb", timezone="Europe/Moscow", is_active=True
            )
            city_b = City(
                id=uuid4(), name="Казань", slug="kzn", timezone="Europe/Moscow", is_active=True
            )

            super_admin = AdminAccount(
                id=uuid4(),
                name="Owner",
                login="owner",
                role=AdminRole.SUPER_ADMIN,
                password_hash="x",
                is_active=True,
            )
            franchise = AdminAccount(
                id=uuid4(),
                name="Франшиза Питер",
                login="spb-partner",
                role=AdminRole.FRANCHISE,
                password_hash="x",
                cities=[city_a],
                is_active=True,
            )

            locker_a = LockerLocation(
                id=uuid4(),
                city_id=city_a.id,
                name="СПб-1",
                address="Невский, 1",
                status=LockerStatus.ONLINE,
            )
            locker_b = LockerLocation(
                id=uuid4(),
                city_id=city_b.id,
                name="Казань-1",
                address="Баумана, 1",
                status=LockerStatus.ONLINE,
            )
            cell_b = LockerCell(
                id=uuid4(),
                locker_id=locker_b.id,
                label="B1",
                status=LockerCellStatus.VACANT,
                supports_return=True,
            )

            category = ProductCategory(
                id=uuid4(), name="Техника", slug="tech", is_active=True, sort_order=0
            )
            product = Product(
                id=uuid4(), category_id=category.id, name="Пылесос", slug="vacuum", is_active=True
            )
            unit_a = InventoryUnit(
                id=uuid4(), product_id=product.id, status=InventoryStatus.RENTED
            )
            unit_b = InventoryUnit(
                id=uuid4(), product_id=product.id, status=InventoryStatus.RENTED
            )

            # user_a — «свой» по городу, user_b — чужой,
            # user_cross — из другого города, но арендует в постамате франшизы.
            user_a = User(
                id=uuid4(),
                phone="+79990000001",
                preferred_city_id=city_a.id,
                verification_status=VerificationStatus.PENDING_REVIEW,
            )
            user_b = User(
                id=uuid4(),
                phone="+79990000002",
                preferred_city_id=city_b.id,
                verification_status=VerificationStatus.PENDING_REVIEW,
            )
            user_cross = User(
                id=uuid4(),
                phone="+79990000003",
                preferred_city_id=city_b.id,
                verification_status=VerificationStatus.PENDING_REVIEW,
            )

            rental_a = Rental(
                id=uuid4(),
                user_id=user_cross.id,
                inventory_unit_id=unit_a.id,
                pickup_locker_id=locker_a.id,
                # PICKUP_READY, а не ACTIVE: sqlite отдаёт naive datetime, и
                # проверка просрочки в списке аренд на нём падает.
                status=RentalStatus.PICKUP_READY,
                planned_end_at=now + timedelta(days=1),
            )
            rental_b = Rental(
                id=uuid4(),
                user_id=user_b.id,
                inventory_unit_id=unit_b.id,
                pickup_locker_id=locker_b.id,
                status=RentalStatus.PICKUP_READY,
                planned_end_at=now + timedelta(days=1),
            )

            verifications = [
                VerificationRequest(
                    id=uuid4(),
                    user_id=user.id,
                    status=VerificationStatus.PENDING_REVIEW,
                    document_type=DocumentType.PASSPORT_RF,
                    document_number=f"DOC-{index}",
                )
                for index, user in enumerate((user_a, user_b, user_cross))
            ]

            db.add_all(
                [
                    city_a,
                    city_b,
                    super_admin,
                    franchise,
                    locker_a,
                    locker_b,
                    cell_b,
                    category,
                    product,
                    unit_a,
                    unit_b,
                    user_a,
                    user_b,
                    user_cross,
                    rental_a,
                    rental_b,
                    *verifications,
                ]
            )
            await db.commit()

            self.city_a_id = city_a.id
            self.city_b_id = city_b.id
            self.super_admin_id = super_admin.id
            self.franchise_id = franchise.id
            self.locker_a_id = locker_a.id
            self.locker_b_id = locker_b.id
            self.user_a_id = user_a.id
            self.user_b_id = user_b.id
            self.user_cross_id = user_cross.id
            self.rental_a_id = rental_a.id
            self.rental_b_id = rental_b.id

        self.acting_admin_id = self.franchise_id

        async def fake_get_current_admin(request, db):
            account = await db.get(AdminAccount, self.acting_admin_id)
            return account, None

        self.patchers = [
            patch(f"backend.routers.admin.{module}.get_current_admin", new=fake_get_current_admin)
            for module in (
                "auth",
                "cities",
                "dashboard",
                "franchises",
                "lockers",
                "rentals",
                "users",
                "verification_queue",
            )
        ]
        for patcher in self.patchers:
            patcher.start()

    async def asyncTearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        async with test_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.drop_all(
                    sync_conn, tables=list(reversed(TEST_TABLES))
                )
            )
        await test_engine.dispose()

    def _act_as_super_admin(self) -> None:
        self.acting_admin_id = self.super_admin_id

    # ------------------------------------------------------------------
    # Списки режутся по городу
    # ------------------------------------------------------------------

    async def test_users_list_scoped_to_city(self):
        async with TestSessionLocal() as db:
            response = await admin_users_router.list_admin_users(
                _make_request(),
                db,
                page=1,
                limit=20,
                q=None,
                verification_status=None,
                is_blocked=None,
            )
        ids = {item["id"] for item in response["data"]["users"]}
        # Свой город + клиент из другого города, арендующий в постамате франшизы.
        self.assertEqual(ids, {str(self.user_a_id), str(self.user_cross_id)})

        self._act_as_super_admin()
        async with TestSessionLocal() as db:
            response = await admin_users_router.list_admin_users(
                _make_request(),
                db,
                page=1,
                limit=20,
                q=None,
                verification_status=None,
                is_blocked=None,
            )
        self.assertEqual(response["meta"]["total"], 3)

    async def test_foreign_user_card_is_forbidden(self):
        async with TestSessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await admin_users_router.get_admin_user(
                    _make_request(), str(self.user_b_id), db
                )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_user_card_rentals_are_scoped_and_carry_context(self):
        """Аренды в карточке: свой город, с товаром и постаматом.

        Карточку открывают, когда клиент написал в поддержку, и из неё
        проваливаются в аренду. Значит показывать можно только то, что
        франшиза потом сможет открыть: `/api/admin/rentals/{id}` для чужого
        города ответит 403, и ссылка вела бы в тупик.
        """
        now = datetime.now(timezone.utc)
        foreign_rental_id = uuid4()
        async with TestSessionLocal() as db:
            product_id = (await db.scalars(select(Product.id))).first()
            foreign_unit = InventoryUnit(
                id=uuid4(), product_id=product_id, status=InventoryStatus.RENTED
            )
            db.add_all(
                [
                    foreign_unit,
                    Rental(
                        id=foreign_rental_id,
                        user_id=self.user_cross_id,
                        inventory_unit_id=foreign_unit.id,
                        pickup_locker_id=self.locker_b_id,
                        status=RentalStatus.PICKUP_READY,
                        planned_end_at=now + timedelta(days=1),
                    ),
                ]
            )
            await db.commit()

        async with TestSessionLocal() as db:
            response = await admin_users_router.get_admin_user(
                _make_request(), str(self.user_cross_id), db
            )
        rentals = response["data"]["rentals"]
        self.assertEqual([item["id"] for item in rentals], [str(self.rental_a_id)])
        self.assertEqual(rentals[0]["productName"], "Пылесос")
        self.assertEqual(rentals[0]["pickupLockerName"], "СПб-1")
        self.assertEqual(rentals[0]["cityName"], "Питер")
        self.assertFalse(rentals[0]["isOverdue"])

        self._act_as_super_admin()
        async with TestSessionLocal() as db:
            response = await admin_users_router.get_admin_user(
                _make_request(), str(self.user_cross_id), db
            )
        self.assertEqual(
            {item["id"] for item in response["data"]["rentals"]},
            {str(self.rental_a_id), str(foreign_rental_id)},
        )

    async def test_rentals_list_scoped_and_city_filter_cannot_widen(self):
        async with TestSessionLocal() as db:
            response = await admin_rentals_router.list_rentals(
                _make_request(),
                db,
                status=None,
                city_id=self.city_b_id,
                locker_id=None,
                overdue_only=False,
                page=1,
                limit=50,
            )
        ids = {item["id"] for item in response["data"]["rentals"]}
        self.assertEqual(ids, {str(self.rental_a_id)})

    async def test_foreign_rental_actions_are_forbidden(self):
        async with TestSessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await admin_rentals_router.get_rental(str(self.rental_b_id), _make_request(), db)
            self.assertEqual(ctx.exception.status_code, 403)

            with self.assertRaises(HTTPException) as ctx:
                await admin_rentals_router.cancel_rental(
                    str(self.rental_b_id), _make_request(), db
                )
            self.assertEqual(ctx.exception.status_code, 403)

    async def test_lockers_scoped_and_foreign_locker_forbidden(self):
        async with TestSessionLocal() as db:
            response = await admin_lockers_router.list_admin_lockers(_make_request(), db)
        ids = {item["id"] for item in response["data"]["lockers"]}
        self.assertEqual(ids, {str(self.locker_a_id)})

        async with TestSessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await admin_lockers_router.get_admin_locker(
                    _make_request(), self.locker_b_id, db
                )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_verification_queue_scoped_to_city(self):
        async with TestSessionLocal() as db:
            response = await admin_verification_router.verification_queue(
                _make_request(), db
            )
        ids = {item["userId"] for item in response["data"]["items"]}
        self.assertEqual(ids, {str(self.user_a_id), str(self.user_cross_id)})

    async def test_cities_list_returns_own_city_only(self):
        async with TestSessionLocal() as db:
            response = await admin_cities_router.list_admin_cities(_make_request(), db)
        ids = [item["id"] for item in response["data"]["cities"]]
        self.assertEqual(ids, [str(self.city_a_id)])

    async def test_city_mutations_forbidden_for_franchise(self):
        payload = AdminCreateCityPayload(
            name="Новый", slug="new", timezone="Europe/Moscow"
        )
        async with TestSessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await admin_cities_router.create_admin_city(_make_request(), payload, db)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_dashboard_counts_only_own_city(self):
        from backend.routers.admin import dashboard as dashboard_router

        async with TestSessionLocal() as db:
            response = await dashboard_router.get_dashboard_overview(_make_request(), db)
        metrics = response["data"]["metrics"]
        self.assertEqual(metrics["cities"], 1)
        self.assertEqual(metrics["lockers"], 1)
        self.assertEqual(metrics["users"], 2)

    async def test_hidden_sections_reject_franchise(self):
        async with TestSessionLocal() as db:
            franchise = await db.get(AdminAccount, self.franchise_id)
            owner = await db.get(AdminAccount, self.super_admin_id)

        with self.assertRaises(HTTPException) as ctx:
            require_not_franchise(franchise)
        self.assertEqual(ctx.exception.status_code, 403)
        # Владелец сети проходит обе проверки.
        require_not_franchise(owner)
        require_super_admin(owner)

        with self.assertRaises(HTTPException):
            require_super_admin(franchise)

    # ------------------------------------------------------------------
    # Управление франшизами
    # ------------------------------------------------------------------

    async def test_create_disable_and_change_password(self):
        self._act_as_super_admin()
        payload = AdminCreateFranchisePayload(
            name="Франшиза Казань",
            login="  KZN-Partner ",
            password="secret12345",
            cityIds=[self.city_b_id],
        )
        async with TestSessionLocal() as db:
            created = await franchises_router.create_franchise(_make_request(), payload, db)
        new_id = created["data"]["franchise"]["id"]
        self.assertEqual(created["data"]["franchise"]["login"], "kzn-partner")
        self.assertEqual(
            [city["name"] for city in created["data"]["franchise"]["cities"]],
            ["Казань"],
        )
        self.assertTrue(created["data"]["franchise"]["isActive"])

        # Живая сессия, которую должно отозвать выключением доступа.
        async with TestSessionLocal() as db:
            db.add(
                AdminAuthSession(
                    id=uuid4(),
                    admin_account_id=uuid4().__class__(new_id),
                    refresh_token_hash="hash-1",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                )
            )
            await db.commit()

        async with TestSessionLocal() as db:
            await franchises_router.update_franchise(
                _make_request(),
                uuid4().__class__(new_id),
                AdminUpdateFranchisePayload(isActive=False),
                db,
            )

        async with TestSessionLocal() as db:
            account = await db.get(AdminAccount, uuid4().__class__(new_id))
            self.assertFalse(account.is_active)
            sessions = (
                await db.scalars(
                    select(AdminAuthSession).where(
                        AdminAuthSession.admin_account_id == account.id
                    )
                )
            ).all()
            self.assertTrue(all(item.revoked_at is not None for item in sessions))

        # Выключенный аккаунт не пускают внутрь.
        async with TestSessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await admin_auth_router.login(
                    _make_request(),
                    AdminLoginPayload(login="kzn-partner", password="secret12345"),
                    db,
                )
            self.assertEqual(ctx.exception.status_code, 403)

        async with TestSessionLocal() as db:
            await franchises_router.change_franchise_password(
                _make_request(),
                uuid4().__class__(new_id),
                AdminFranchisePasswordPayload(password="brand-new-pass"),
                db,
            )

        async with TestSessionLocal() as db:
            account = await db.get(AdminAccount, uuid4().__class__(new_id))
            self.assertTrue(verify_password("brand-new-pass", account.password_hash))

    async def test_duplicate_login_rejected(self):
        self._act_as_super_admin()
        payload = AdminCreateFranchisePayload(
            name="Дубль",
            login="spb-partner",
            password="secret12345",
            cityIds=[self.city_b_id],
        )
        async with TestSessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await franchises_router.create_franchise(_make_request(), payload, db)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_franchise_cannot_manage_franchises(self):
        async with TestSessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await franchises_router.list_franchises(_make_request(), db)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_stats_are_city_scoped(self):
        self._act_as_super_admin()
        async with TestSessionLocal() as db:
            response = await franchises_router.get_franchise_stats(
                _make_request(), self.franchise_id, db
            )
        stats = response["data"]["stats"]
        self.assertEqual(stats["lockers"]["total"], 1)
        self.assertEqual(stats["rentals"]["total"], 1)
        self.assertEqual(stats["rentals"]["active"], 1)
        self.assertEqual(stats["users"]["total"], 2)

    # ------------------------------------------------------------------
    # Уведомления
    # ------------------------------------------------------------------

    async def test_notifications_are_addressed_by_city(self):
        async with TestSessionLocal() as db:
            db.add_all(
                [
                    TelegramAdminSubscriber(
                        id=uuid4(), username="network", chat_id=1, is_enabled=True
                    ),
                    TelegramAdminSubscriber(
                        id=uuid4(),
                        username="spbpartner",
                        chat_id=2,
                        is_enabled=True,
                        city_id=self.city_a_id,
                    ),
                    TelegramAdminSubscriber(
                        id=uuid4(),
                        username="kznpartner",
                        chat_id=3,
                        is_enabled=True,
                        city_id=self.city_b_id,
                    ),
                ]
            )
            await db.commit()

            self.assertEqual(await get_active_chat_ids(db), ["1"])
            self.assertEqual(
                sorted(await get_active_chat_ids(db, city_id=self.city_a_id)), ["1", "2"]
            )
            self.assertEqual(
                sorted(await get_active_chat_ids(db, city_id=self.city_b_id)), ["1", "3"]
            )

    async def test_franchise_sees_only_own_subscribers(self):
        from backend.routers.admin import telegram_subscribers as subs_router

        async def fake_get_current_admin(request, db):
            account = await db.get(AdminAccount, self.acting_admin_id)
            return account, None

        with patch.object(subs_router, "get_current_admin", new=fake_get_current_admin):
            async with TestSessionLocal() as db:
                created = await subs_router.create_telegram_subscriber(
                    _make_request(),
                    db,
                    subs_router.CreateSubscriberPayload(username="spbpartner"),
                )
            self.assertEqual(created["data"]["subscriber"]["cityId"], str(self.city_a_id))

            async with TestSessionLocal() as db:
                db.add(
                    TelegramAdminSubscriber(
                        id=uuid4(),
                        username="kznpartner",
                        chat_id=9,
                        is_enabled=True,
                        city_id=self.city_b_id,
                    )
                )
                await db.commit()

            async with TestSessionLocal() as db:
                listed = await subs_router.list_telegram_subscribers(_make_request(), db)
        usernames = {item["username"] for item in listed["data"]["items"]}
        self.assertEqual(usernames, {"spbpartner"})


    async def test_max_notifications_are_addressed_by_city(self):
        async with TestSessionLocal() as db:
            db.add_all(
                [
                    MaxAdminSubscriber(
                        id=uuid4(), username="network", chat_id=11, is_enabled=True
                    ),
                    MaxAdminSubscriber(
                        id=uuid4(),
                        username="spbpartner",
                        user_id=22,
                        is_enabled=True,
                        city_id=self.city_a_id,
                    ),
                    MaxAdminSubscriber(
                        id=uuid4(),
                        username="kznpartner",
                        chat_id=33,
                        is_enabled=True,
                        city_id=self.city_b_id,
                    ),
                ]
            )
            await db.commit()

            self.assertEqual(await get_active_recipients(db), [("chat_id", 11)])
            self.assertEqual(
                sorted(await get_active_recipients(db, city_id=self.city_a_id)),
                [("chat_id", 11), ("user_id", 22)],
            )
            self.assertEqual(
                sorted(await get_active_recipients(db, city_id=self.city_b_id)),
                [("chat_id", 11), ("chat_id", 33)],
            )

    async def test_franchise_sees_only_own_max_subscribers(self):
        from backend.routers.admin import max_subscribers as max_router

        async def fake_get_current_admin(request, db):
            account = await db.get(AdminAccount, self.acting_admin_id)
            return account, None

        with patch.object(max_router, "get_current_admin", new=fake_get_current_admin):
            async with TestSessionLocal() as db:
                created = await max_router.create_max_subscriber(
                    _make_request(),
                    db,
                    max_router.CreateSubscriberPayload(username="spbpartner"),
                )
            self.assertEqual(created["data"]["subscriber"]["cityId"], str(self.city_a_id))
            self.assertEqual(created["data"]["subscriber"]["cityName"], "Питер")

            async with TestSessionLocal() as db:
                db.add(
                    MaxAdminSubscriber(
                        id=uuid4(),
                        username="kznpartner",
                        chat_id=99,
                        is_enabled=True,
                        city_id=self.city_b_id,
                    )
                )
                await db.commit()

            async with TestSessionLocal() as db:
                listed = await max_router.list_max_subscribers(_make_request(), db)
            usernames = {item["username"] for item in listed["data"]["items"]}
            self.assertEqual(usernames, {"spbpartner"})

            # Чужой подписчик для франшизы просто не существует.
            async with TestSessionLocal() as db:
                foreign = await db.scalar(
                    select(MaxAdminSubscriber).where(
                        MaxAdminSubscriber.username == "kznpartner"
                    )
                )
                with self.assertRaises(HTTPException) as ctx:
                    await max_router.delete_max_subscriber(
                        _make_request(), foreign.id, db
                    )
                self.assertEqual(ctx.exception.status_code, 404)

    async def test_max_webhook_setup_is_closed_for_franchise(self):
        from backend.routers.admin import max_subscribers as max_router

        async def fake_get_current_admin(request, db):
            account = await db.get(AdminAccount, self.acting_admin_id)
            return account, None

        with patch.object(max_router, "get_current_admin", new=fake_get_current_admin):
            async with TestSessionLocal() as db:
                with self.assertRaises(HTTPException) as ctx:
                    await max_router.setup_max_webhook(_make_request(), db)
            self.assertEqual(ctx.exception.status_code, 403)


    # ------------------------------------------------------------------
    # Несколько городов у одной франшизы
    # ------------------------------------------------------------------

    async def _give_franchise_second_city(self) -> None:
        """Выдаёт питерской франшизе ещё и Казань."""

        async with TestSessionLocal() as db:
            account = await db.get(AdminAccount, self.franchise_id)
            city_b = await db.get(City, self.city_b_id)
            account.cities = list(account.cities) + [city_b]
            await db.commit()

    async def test_two_cities_widen_the_scope(self):
        await self._give_franchise_second_city()

        async with TestSessionLocal() as db:
            lockers = await admin_lockers_router.list_admin_lockers(
                _make_request(), db
            )
            rentals = await admin_rentals_router.list_rentals(
                _make_request(),
                db,
                status=None,
                city_id=None,
                locker_id=None,
                overdue_only=False,
                page=1,
                limit=50,
            )
            users = await admin_users_router.list_admin_users(
                _make_request(),
                db,
                page=1,
                limit=20,
                q=None,
                verification_status=None,
                is_blocked=None,
            )

        self.assertEqual(
            {item["id"] for item in lockers["data"]["lockers"]},
            {str(self.locker_a_id), str(self.locker_b_id)},
        )
        self.assertEqual(
            {item["id"] for item in rentals["data"]["rentals"]},
            {str(self.rental_a_id), str(self.rental_b_id)},
        )
        # Оба города плюс клиент, приехавший из другого города.
        self.assertEqual(
            {item["id"] for item in users["data"]["users"]},
            {str(self.user_a_id), str(self.user_b_id), str(self.user_cross_id)},
        )

    async def test_second_city_object_is_no_longer_foreign(self):
        # До выдачи второго города аренда соседнего города — чужая...
        async with TestSessionLocal() as db:
            account = await db.get(AdminAccount, self.franchise_id)
            rental_b = await db.get(Rental, self.rental_b_id)
            with self.assertRaises(HTTPException) as ctx:
                await ensure_rental_in_scope(db, franchise_city_ids(account), rental_b)
        self.assertEqual(ctx.exception.status_code, 403)

        # ...а после — своя, проверка молча пропускает.
        await self._give_franchise_second_city()
        async with TestSessionLocal() as db:
            account = await db.get(AdminAccount, self.franchise_id)
            rental_b = await db.get(Rental, self.rental_b_id)
            await ensure_rental_in_scope(db, franchise_city_ids(account), rental_b)

    async def test_franchise_without_cities_gets_403(self):
        async with TestSessionLocal() as db:
            account = await db.get(AdminAccount, self.franchise_id)
            account.cities = []
            await db.commit()

        async with TestSessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await admin_lockers_router.list_admin_lockers(_make_request(), db)
        # Пустой скоуп — это 403, а не «показать всё».
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_create_franchise_with_two_cities(self):
        self._act_as_super_admin()
        payload = AdminCreateFranchisePayload(
            name="Франшиза Северо-Запад",
            login="nw-partner",
            password="secret12345",
            cityIds=[self.city_a_id, self.city_b_id],
        )
        async with TestSessionLocal() as db:
            created = await franchises_router.create_franchise(
                _make_request(), payload, db
            )

        names = [city["name"] for city in created["data"]["franchise"]["cities"]]
        self.assertEqual(sorted(names), ["Казань", "Питер"])

    async def test_changing_cities_revokes_sessions(self):
        # Живая сессия франчайзи: смена городов должна её закрыть.
        async with TestSessionLocal() as db:
            db.add(
                AdminAuthSession(
                    id=uuid4(),
                    admin_account_id=self.franchise_id,
                    refresh_token_hash="hash",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                )
            )
            await db.commit()

        self._act_as_super_admin()
        async with TestSessionLocal() as db:
            await franchises_router.update_franchise(
                _make_request(),
                self.franchise_id,
                AdminUpdateFranchisePayload(cityIds=[self.city_a_id, self.city_b_id]),
                db,
            )

        async with TestSessionLocal() as db:
            account = await db.get(AdminAccount, self.franchise_id)
            self.assertEqual(
                sorted(city.name for city in account.cities), ["Казань", "Питер"]
            )
            revoked = (
                await db.scalars(
                    select(AdminAuthSession.revoke_reason).where(
                        AdminAuthSession.admin_account_id == self.franchise_id
                    )
                )
            ).all()
        self.assertEqual(list(revoked), ["city_changed"])

    async def test_city_given_to_franchise_cannot_be_deleted(self):
        self._act_as_super_admin()
        async with TestSessionLocal() as db:
            with self.assertRaises(HTTPException) as ctx:
                await admin_cities_router.delete_admin_city(
                    _make_request(), self.city_a_id, db
                )
        # Иначе франчайзи остался бы без городов и без админки.
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_multi_city_franchise_picks_subscriber_city(self):
        from backend.routers.admin import telegram_subscribers as tg_router

        await self._give_franchise_second_city()

        async def fake_get_current_admin(request, db):
            account = await db.get(AdminAccount, self.acting_admin_id)
            return account, None

        with patch.object(tg_router, "get_current_admin", new=fake_get_current_admin):
            async with TestSessionLocal() as db:
                # Городов несколько — без выбора не создаём.
                with self.assertRaises(HTTPException) as ctx:
                    await tg_router.create_telegram_subscriber(
                        _make_request(),
                        db,
                        tg_router.CreateSubscriberPayload(username="nwpartner"),
                    )
                self.assertEqual(ctx.exception.status_code, 400)

                # Чужой город — тоже нет.
                with self.assertRaises(HTTPException) as ctx:
                    await tg_router.create_telegram_subscriber(
                        _make_request(),
                        db,
                        tg_router.CreateSubscriberPayload(
                            username="nwpartner", cityId=uuid4()
                        ),
                    )
                self.assertEqual(ctx.exception.status_code, 403)

                created = await tg_router.create_telegram_subscriber(
                    _make_request(),
                    db,
                    tg_router.CreateSubscriberPayload(
                        username="nwpartner", cityId=self.city_b_id
                    ),
                )
        self.assertEqual(created["data"]["subscriber"]["cityId"], str(self.city_b_id))


if __name__ == "__main__":
    unittest.main()
