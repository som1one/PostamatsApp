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
from backend.core.settings import settings  # noqa: E402
from backend.models.admin_account import AdminAccount  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.condition_report import ConditionReport  # noqa: E402
from backend.models.condition_report_photo import ConditionReportPhoto  # noqa: E402
from backend.models.enums import (  # noqa: E402
    AdminRole,
    ConditionReportType,
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    MediaFileKind,
    PaymentStatus,
    PaymentType,
    RentalStatus,
    ReservationStatus,
    ReturnRequestStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.media_file import MediaFile  # noqa: E402
from backend.models.payment import Payment  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.rental import Rental  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.return_request import ReturnRequest  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.routers.admin import rentals as admin_rentals_router  # noqa: E402
from backend.utils import return_photos as return_photos_utils  # noqa: E402
from backend.utils.admin_auth_utils import hash_password  # noqa: E402
from backend.utils.products_utils import public_media_url  # noqa: E402


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
            self.unit_id = unit.id
            self.locker_id = locker.id
            self.cell_id = cell.id
            self.past_rental_id = past_rental.id

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

    async def _detail(self, rental_id=None) -> dict:
        async with SessionLocal() as db:
            payload = await admin_rentals_router.get_rental(
                str(rental_id or self.rental_id), _make_request(), db
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
        self.assertEqual(detail["cell"]["lockerId"], str(self.locker_id))
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

    # --- Блок «Фото при возврате» ---------------------------------------

    async def _complete_return(self) -> datetime:
        """Возврат прошёл через постамат: аренда закрыта, заявка COMPLETED."""
        completed_at = self.now - timedelta(minutes=12)
        async with SessionLocal() as db:
            rental = await db.get(Rental, self.rental_id)
            rental.status = RentalStatus.COMPLETED
            rental.completed_at = completed_at
            rental.actual_end_at = completed_at
            rental.return_locker_id = self.locker_id
            unit = await db.get(InventoryUnit, self.unit_id)
            unit.status = InventoryStatus.AWAITING_CONFIRMATION
            db.add(
                ReturnRequest(
                    id=uuid4(),
                    rental_id=self.rental_id,
                    locker_id=self.locker_id,
                    cell_id=self.cell_id,
                    pin="4821",
                    status=ReturnRequestStatus.COMPLETED,
                    requested_at=completed_at - timedelta(minutes=5),
                    deadline_at=completed_at + timedelta(minutes=25),
                    completed_at=completed_at,
                )
            )
            await db.commit()
        return completed_at

    async def _attach_photos(self, *, sort_orders: list[int], note: str | None) -> list:
        """Отчёт с фото; ``sort_orders`` — порядок, в котором их снял клиент."""
        async with SessionLocal() as db:
            files = [
                MediaFile(
                    id=uuid4(),
                    storage_provider="filesystem",
                    bucket="filesystem-private",
                    file_key=f"condition/2026/09/14/{uuid4().hex}-shot-{index}.jpg",
                    mime_type="image/jpeg",
                    file_size=120_000 + index,
                    original_name=f"shot-{index}.jpg",
                    kind=MediaFileKind.CONDITION_PHOTO_AFTER,
                    uploaded_by_user_id=self.user_id,
                    created_at=self.now,
                )
                for index in range(len(sort_orders))
            ]
            report = ConditionReport(
                id=uuid4(),
                inventory_unit_id=self.unit_id,
                rental_id=self.rental_id,
                report_type=ConditionReportType.AFTER_RETURN,
                note=note,
                created_by_user_id=self.user_id,
            )
            db.add_all([*files, report])
            await db.flush()
            for media, sort_order in zip(files, sort_orders):
                db.add(
                    ConditionReportPhoto(
                        condition_report_id=report.id,
                        file_id=media.id,
                        sort_order=sort_order,
                    )
                )
            await db.commit()
            ordered = sorted(zip(sort_orders, files), key=lambda pair: pair[0])
            return [(media.id, media.file_key, media.file_size) for _, media in ordered]

    async def test_no_return_means_no_report(self):
        """Аренда ещё на руках — блока нет вовсе, а не «без фото»."""
        detail = await self._detail()
        self.assertIsNone(detail["returnReport"])
        self.assertIsNone(detail["rental"]["returnReport"])

    async def test_returned_without_photos_is_expected_empty(self):
        completed_at = await self._complete_return()

        report = (await self._detail())["returnReport"]
        self.assertEqual(
            report,
            {
                "id": None,
                "createdAt": None,
                "note": None,
                "source": None,
                "photos": [],
                "photoCount": 0,
                "expected": True,
                "returnedAt": report["returnedAt"],
                # Юнит ждёт проверки именно этого возврата.
                "pendingReview": True,
                # Фото пока нет, но клиент ещё может дослать.
                "attachPhotosUntil": report["attachPhotosUntil"],
            },
        )
        self.assertEqual(datetime.fromisoformat(report["returnedAt"]), completed_at)
        self.assertEqual(
            datetime.fromisoformat(report["attachPhotosUntil"]),
            completed_at + timedelta(minutes=settings.RETURN_PHOTO_LATE_WINDOW_MINUTES),
        )

    async def test_attach_photos_until_is_null_once_the_window_closed(self):
        await self._complete_return()

        # Возврат был 12 минут назад, окно — 5 минут: ждать фото больше нечего.
        with patch.object(settings, "RETURN_PHOTO_LATE_WINDOW_MINUTES", 5):
            report = (await self._detail())["returnReport"]

        self.assertEqual(report["photoCount"], 0)
        self.assertIsNone(report["attachPhotosUntil"])
        self.assertTrue(report["pendingReview"])

    async def _complete_past_return_with_photo(self) -> None:
        """Старая аренда того же юнита тоже вернулась через постамат, с фото."""
        past_completed_at = self.now - timedelta(days=10)
        async with SessionLocal() as db:
            past = await db.get(Rental, self.past_rental_id)
            past.completed_at = past_completed_at
            media = MediaFile(
                id=uuid4(),
                storage_provider="filesystem",
                bucket="filesystem-private",
                file_key=f"condition/2026/09/04/{uuid4().hex}-old.jpg",
                mime_type="image/jpeg",
                file_size=90_000,
                kind=MediaFileKind.CONDITION_PHOTO_AFTER,
                uploaded_by_user_id=self.user_id,
                created_at=past_completed_at,
            )
            report = ConditionReport(
                id=uuid4(),
                inventory_unit_id=self.unit_id,
                rental_id=self.past_rental_id,
                report_type=ConditionReportType.AFTER_RETURN,
                note="Старый возврат, всё цело",
                created_by_user_id=self.user_id,
            )
            db.add_all(
                [
                    ReturnRequest(
                        id=uuid4(),
                        rental_id=self.past_rental_id,
                        locker_id=self.locker_id,
                        cell_id=self.cell_id,
                        pin="1111",
                        status=ReturnRequestStatus.COMPLETED,
                        requested_at=past_completed_at - timedelta(minutes=5),
                        deadline_at=past_completed_at + timedelta(minutes=25),
                        completed_at=past_completed_at,
                    ),
                    media,
                    report,
                ]
            )
            await db.flush()
            db.add(ConditionReportPhoto(condition_report_id=report.id, file_id=media.id, sort_order=0))
            await db.commit()

    async def test_review_is_offered_only_on_the_return_the_unit_waits_for(self):
        await self._complete_past_return_with_photo()
        await self._complete_return()

        current = (await self._detail())["returnReport"]
        past = (await self._detail(self.past_rental_id))["returnReport"]

        self.assertTrue(current["pendingReview"])
        # У старой аренды фото есть и юнит «На проверке», но ждёт он не её.
        self.assertEqual(past["photoCount"], 1)
        self.assertFalse(past["pendingReview"])
        self.assertIsNone(past["attachPhotosUntil"])

        # Юнит проверили — кнопок нет ни у кого.
        async with SessionLocal() as db:
            unit = await db.get(InventoryUnit, self.unit_id)
            unit.status = InventoryStatus.AVAILABLE
            await db.commit()
        self.assertFalse((await self._detail())["returnReport"]["pendingReview"])

    async def test_photos_come_in_client_order_with_public_urls(self):
        completed_at = await self._complete_return()
        # Вставляем кадры не в том порядке, в котором их снимали.
        expected = await self._attach_photos(sort_orders=[2, 0, 1], note="Царапина на ручке")

        # Как на проде: filesystem-хранилище отдаёт относительный путь.
        with patch.object(settings, "STORAGE_PROVIDER", "filesystem"), patch.object(
            settings, "MEDIA_PUBLIC_BASE_URL", ""
        ):
            detail = await self._detail()
            expected_urls = [public_media_url(file_key) for _, file_key, _ in expected]

        report = detail["returnReport"]
        self.assertIsNotNone(report["id"])
        self.assertIsNotNone(report["createdAt"])
        self.assertEqual(report["note"], "Царапина на ручке")
        self.assertEqual(report["source"], "user")
        self.assertTrue(report["expected"])
        self.assertEqual(datetime.fromisoformat(report["returnedAt"]), completed_at)
        self.assertEqual(report["photoCount"], 3)
        self.assertEqual(
            [photo["id"] for photo in report["photos"]],
            [str(file_id) for file_id, _, _ in expected],
        )
        self.assertEqual([photo["url"] for photo in report["photos"]], expected_urls)
        self.assertTrue(expected_urls[0].startswith("/assets/runtime-uploads/condition/"))
        self.assertEqual(
            [photo["fileSize"] for photo in report["photos"]],
            [file_size for _, _, file_size in expected],
        )
        self.assertEqual({photo["mimeType"] for photo in report["photos"]}, {"image/jpeg"})
        self.assertTrue(report["pendingReview"])
        self.assertIsNone(report["attachPhotosUntil"])
        # Клиентский returnReport в data.rental никуда не делся.
        self.assertEqual(len(detail["rental"]["returnReport"]["photos"]), 3)

    async def test_report_is_loaded_once_for_both_payloads(self):
        await self._complete_return()
        await self._attach_photos(sort_orders=[0], note=None)

        original = return_photos_utils.load_return_report_views
        calls: list[list] = []

        async def spy(db, rental_ids):
            calls.append(list(rental_ids))
            return await original(db, rental_ids)

        with patch.object(admin_rentals_router, "load_return_report_views", new=spy), patch.object(
            return_photos_utils, "load_return_report_views", new=spy
        ):
            detail = await self._detail()

        self.assertEqual(calls, [[self.rental_id]])
        self.assertEqual(detail["returnReport"]["photoCount"], 1)
        self.assertEqual(len(detail["rental"]["returnReport"]["photos"]), 1)


if __name__ == "__main__":
    unittest.main()
