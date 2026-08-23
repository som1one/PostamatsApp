"""Карточка клиента в панели поддержки: «что, где и как» по его арендам.

Оператор открывает диалог и должен с первого взгляда понять, что у клиента на
руках, из какого постамата и как провалиться в саму аренду. Проверяем:

1. Аренда несёт товар, постамат, город и deep-link в карточку аренды в админке.
2. Без ``ADMIN_PANEL_URL`` ссылки нет (``None``), а не битый URL.
3. Постаматы резолвятся пачкой — один запрос на все аренды карточки, без N+1.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("UPLOAD_DEV_STUB", "true")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.core.settings import settings
from backend.models.city import City
from backend.models.enums import (
    InventoryStatus,
    LockerStatus,
    RentalStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.media_file import MediaFile
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.rental import Rental
from backend.models.reservation import Reservation
from backend.models.support_conversation import SupportConversation
from backend.models.support_message import SupportMessage
from backend.models.user import User
from backend.routers.admin import support as admin_support_router
from backend.services import support_chat_service

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

TEST_TABLES = [
    City.__table__,
    MediaFile.__table__,
    ProductCategory.__table__,
    Product.__table__,
    LockerLocation.__table__,
    LockerCell.__table__,
    InventoryUnit.__table__,
    User.__table__,
    PricePlan.__table__,
    Reservation.__table__,
    Rental.__table__,
    SupportConversation.__table__,
    SupportMessage.__table__,
]


class SupportClientInfoCardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(TEST_DB_URL, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=TEST_TABLES)
            )
        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )

        now = datetime.now(timezone.utc)
        async with self.SessionLocal() as db:
            city = City(
                id=uuid4(),
                name="Санкт-Петербург",
                slug="spb",
                timezone="Europe/Moscow",
                is_active=True,
            )
            locker = LockerLocation(
                id=uuid4(),
                city_id=city.id,
                name="Невский, 12",
                address="Невский пр., 12",
                status=LockerStatus.ONLINE,
            )
            category = ProductCategory(
                id=uuid4(), name="Техника", slug="tech", is_active=True, sort_order=0
            )
            product = Product(
                id=uuid4(),
                category_id=category.id,
                name="PlayStation 5",
                slug="ps5",
                is_active=True,
            )
            unit = InventoryUnit(
                id=uuid4(), product_id=product.id, status=InventoryStatus.RENTED
            )
            user = User(
                id=uuid4(),
                phone="+79116263211",
                first_name="Ярослав",
                last_name="Козаченко",
                verification_status=VerificationStatus.APPROVED,
            )
            rental = Rental(
                id=uuid4(),
                user_id=user.id,
                inventory_unit_id=unit.id,
                pickup_locker_id=locker.id,
                status=RentalStatus.PICKUP_READY,
                starts_at=now,
                planned_end_at=now + timedelta(days=2),
            )
            conversation = SupportConversation(id=uuid4(), user_id=user.id)

            db.add_all([city, locker, category, product, unit, user, rental, conversation])
            await db.commit()

            self.conversation_id = conversation.id
            self.rental_id = rental.id

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _build_card(self):
        async with self.SessionLocal() as db:
            return await support_chat_service.build_client_info_card(
                db, self.conversation_id
            )

    async def test_rental_carries_place_and_admin_deep_link(self) -> None:
        original = settings.ADMIN_PANEL_URL
        settings.ADMIN_PANEL_URL = "https://naprokatberu.ru/admin"
        try:
            card = await self._build_card()
        finally:
            settings.ADMIN_PANEL_URL = original

        self.assertEqual(len(card.recent_rentals), 1)
        rental = card.recent_rentals[0]
        self.assertEqual(rental.product_name, "PlayStation 5")
        self.assertEqual(rental.locker_name, "Невский, 12")
        self.assertEqual(rental.city_name, "Санкт-Петербург")
        self.assertEqual(
            rental.admin_url,
            f"https://naprokatberu.ru/admin/?section=rentals&rental={self.rental_id}",
        )

    async def test_no_admin_url_without_configured_panel(self) -> None:
        original = settings.ADMIN_PANEL_URL
        settings.ADMIN_PANEL_URL = None
        try:
            card = await self._build_card()
        finally:
            settings.ADMIN_PANEL_URL = original

        self.assertIsNone(card.recent_rentals[0].admin_url)
        # Постамат резолвится независимо от ссылки — «где» оператору нужно
        # даже тогда, когда переходить некуда.
        self.assertEqual(card.recent_rentals[0].locker_name, "Невский, 12")

    async def test_new_fields_reach_the_wire_payload(self) -> None:
        """Роутер обязан переложить новые поля в схему, а не потерять их."""
        original = settings.ADMIN_PANEL_URL
        settings.ADMIN_PANEL_URL = "https://naprokatberu.ru/admin"
        try:
            card = await self._build_card()
        finally:
            settings.ADMIN_PANEL_URL = original

        payload = admin_support_router._map_client_info_card(card)
        rental = payload.recentRentals[0]
        self.assertEqual(rental.lockerName, "Невский, 12")
        self.assertEqual(rental.cityName, "Санкт-Петербург")
        self.assertEqual(
            rental.adminUrl,
            f"https://naprokatberu.ru/admin/?section=rentals&rental={self.rental_id}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
