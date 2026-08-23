"""Карточка аренды в админке отдаёт полный контекст, а не четыре поля.

До этого оператор видел статус, PIN, имя с телефоном и две суммы — за всем
остальным (на каких условиях оформили, какой ячейкой пользовался клиент, что
на самом деле произошло с деньгами) приходилось ходить в базу руками.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

TEST_DB_PATH = os.path.abspath(
    f"./backend/tests/test_admin_rental_detail_{uuid4().hex}.sqlite"
)
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
os.environ["ESI_DEV_STUB"] = "true"
os.environ["UPLOAD_DEV_STUB"] = "true"

from fastapi import Request  # noqa: E402

from backend.main import app  # noqa: E402,F401  (регистрирует модели в metadata)
from backend.core.database import Base, SessionLocal, engine  # noqa: E402
from backend.models.admin_account import AdminAccount  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    AdminRole,
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
from backend.routers.admin import rentals as admin_rentals_router  # noqa: E402
from backend.utils.admin_auth_utils import hash_password  # noqa: E402


def _make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "headers": [(b"user-agent", b"pytest")],
            "path": "/api/admin/rentals",
            "client": ("127.0.0.1", 0),
        }
    )


class AdminRentalDetailTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        now = datetime.now(timezone.utc)
        self.now = now

        async with SessionLocal() as db:
            admin = AdminAccount(
                id=uuid4(),
                name="Root",
                login="root",
                role=AdminRole.SUPER_ADMIN,
                password_hash=hash_password("irrelevant-for-this-test"),
            )
            city = City(
                id=uuid4(),
                name="Санкт-Петербург",
                slug="spb",
                timezone="Europe/Moscow",
                is_active=True,
                sort_order=0,
            )
            category = ProductCategory(
                id=uuid4(), name="Клининг", slug="cleaning", is_active=True, sort_order=0
            )
            product = Product(
                id=uuid4(),
                category_id=category.id,
                name="Мощный пылесос",
                slug="vacuum",
                is_active=True,
            )
            plan = PricePlan(
                id=uuid4(),
                product_id=product.id,
                name="Сутки",
                duration_type="day",
                duration_value=1,
                base_amount=Decimal("750.00"),
                currency="RUB",
                is_active=True,
            )
            locker = LockerLocation(
                id=uuid4(),
                city_id=city.id,
                name="ПВЗ Московский",
                address="Московское шоссе, 12",
                status=LockerStatus.ONLINE,
                external_provider="esi",
                external_locker_id="LOCKER-1",
            )
            cell = LockerCell(
                id=uuid4(),
                locker_id=locker.id,
                label="A12",
                external_cell_id="A12",
                status=LockerCellStatus.OCCUPIED,
                supports_return=True,
            )
            unit = InventoryUnit(
                id=uuid4(),
                product_id=product.id,
                locker_cell_id=cell.id,
                status=InventoryStatus.RENTED,
                serial_number="SN-00042",
                barcode="4600000000017",
            )
            user = User(
                id=uuid4(),
                phone="+79995550101",
                email="ivanov@example.com",
                first_name="Иван",
                last_name="Иванов",
                preferred_city_id=city.id,
                verification_status=VerificationStatus.APPROVED,
                created_at=now - timedelta(days=120),
                last_login_at=now - timedelta(hours=3),
            )
            reservation = Reservation(
                id=uuid4(),
                user_id=user.id,
                product_id=product.id,
                inventory_unit_id=unit.id,
                locker_id=locker.id,
                price_plan_id=plan.id,
                status=ReservationStatus.CONFIRMED,
                duration_type="day",
                duration_value=3,
                quoted_amount=Decimal("750.00"),
                preauth_amount=Decimal("750.00"),
                expires_at=now + timedelta(days=2),
                pickup_at=now + timedelta(days=1),
                confirmed_at=now - timedelta(hours=2),
                created_at=now - timedelta(hours=3),
            )
            rental = Rental(
                id=uuid4(),
                user_id=user.id,
                reservation_id=reservation.id,
                inventory_unit_id=unit.id,
                pickup_locker_id=locker.id,
                pickup_pin="5110",
                status=RentalStatus.ACTIVE,
                pickup_expires_at=now + timedelta(hours=3),
                starts_at=now - timedelta(hours=2),
                planned_end_at=now + timedelta(days=1),
            )
            # Вторая, уже завершённая аренда — чтобы счётчики в карточке
            # арендатора считались, а не просто существовали.
            past_rental = Rental(
                id=uuid4(),
                user_id=user.id,
                inventory_unit_id=unit.id,
                pickup_locker_id=locker.id,
                status=RentalStatus.COMPLETED,
                planned_end_at=now - timedelta(days=10),
            )
            payments = [
                Payment(
                    id=uuid4(),
                    user_id=user.id,
                    reservation_id=reservation.id,
                    provider="yookassa",
                    provider_payment_id="yk-captured",
                    type=PaymentType.PREAUTH,
                    status=PaymentStatus.CAPTURED,
                    amount=Decimal("750.00"),
                    currency="RUB",
                ),
                Payment(
                    id=uuid4(),
                    user_id=user.id,
                    reservation_id=reservation.id,
                    provider="yookassa",
                    provider_payment_id="yk-failed",
                    type=PaymentType.PREAUTH,
                    status=PaymentStatus.FAILED,
                    amount=Decimal("750.00"),
                    currency="RUB",
                    failure_code="canceled",
                ),
            ]
            db.add_all(
                [admin, city, category, product, plan, locker, cell, unit, user,
                 reservation, rental, past_rental, *payments]
            )
            await db.commit()

            self.admin_id = admin.id
            self.rental_id = rental.id
            self.user_id = user.id
            self.reservation_id = reservation.id

        async def fake_get_current_admin(request, db):
            return await db.get(AdminAccount, self.admin_id), None

        self.patcher = patch.object(
            admin_rentals_router, "get_current_admin", new=fake_get_current_admin
        )
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        try:
            await engine.dispose()
            if os.path.exists(TEST_DB_PATH):
                os.remove(TEST_DB_PATH)
        except (PermissionError, OSError):
            pass

    async def _detail(self) -> dict:
        async with SessionLocal() as db:
            payload = await admin_rentals_router.get_rental(
                str(self.rental_id), _make_request(), db
            )
        return payload["data"]

    async def test_user_card_carries_profile_and_history(self):
        user = (await self._detail())["user"]
        self.assertEqual(user["id"], str(self.user_id))
        self.assertEqual(user["name"], "Иван Иванов")
        self.assertEqual(user["email"], "ivanov@example.com")
        self.assertEqual(user["cityName"], "Санкт-Петербург")
        self.assertEqual(user["verificationStatus"], "approved")
        self.assertFalse(user["isBlocked"])
        self.assertIsNotNone(user["registeredAt"])
        self.assertIsNotNone(user["lastLoginAt"])
        self.assertEqual(user["rentalsTotal"], 2)
        self.assertEqual(user["rentalsCompleted"], 1)
        self.assertEqual(user["rentalsActive"], 1)
        self.assertEqual(user["rentalsOverdue"], 0)

    async def test_reservation_terms_are_exposed(self):
        res = (await self._detail())["reservation"]
        self.assertEqual(res["id"], str(self.reservation_id))
        self.assertEqual(res["status"], "confirmed")
        self.assertEqual(res["durationType"], "day")
        self.assertEqual(res["durationValue"], 3)
        self.assertEqual(res["quotedAmount"], 75000)
        self.assertEqual(res["currency"], "RUB")
        self.assertEqual(res["pricePlanName"], "Сутки")
        self.assertIsNotNone(res["pickupAt"])
        self.assertIsNotNone(res["confirmedAt"])

    async def test_every_payment_is_listed_with_provider_id(self):
        payments = (await self._detail())["payments"]
        self.assertEqual(len(payments), 2)
        by_provider = {p["providerPaymentId"]: p for p in payments}
        self.assertEqual(by_provider["yk-captured"]["status"], "captured")
        self.assertEqual(by_provider["yk-captured"]["amount"], 75000)
        self.assertEqual(by_provider["yk-failed"]["status"], "failed")
        self.assertEqual(by_provider["yk-failed"]["failureCode"], "canceled")

    async def test_cell_and_locker_context(self):
        detail = await self._detail()
        self.assertEqual(detail["cell"]["label"], "A12")
        self.assertEqual(detail["cell"]["status"], "occupied")
        self.assertEqual(detail["pickupCityName"], "Санкт-Петербург")
        self.assertIsNone(detail["returnLocker"])
        self.assertEqual(detail["inventoryUnit"]["barcode"], "4600000000017")

    async def test_timeline_covers_rental_own_dates(self):
        tl = (await self._detail())["timeline"]
        self.assertIsNotNone(tl["createdAt"])
        self.assertIsNotNone(tl["pickupExpiresAt"])
        self.assertIsNone(tl["completedAt"])
        self.assertFalse(tl["isOverdue"])

    async def test_rental_without_reservation_does_not_break(self):
        """Аренда, созданная админом напрямую, не должна ронять карточку."""
        async with SessionLocal() as db:
            rental = await db.get(Rental, self.rental_id)
            rental.reservation_id = None
            await db.commit()

        detail = await self._detail()
        self.assertIsNone(detail["reservation"])
        # Платежи брони отвалились вместе со ссылкой, но карточка живая.
        self.assertEqual(detail["payments"], [])
        self.assertEqual(detail["user"]["name"], "Иван Иванов")


if __name__ == "__main__":
    unittest.main()
