"""Деплой не должен удалять брони, аренды и платежи.

2026-10-23 клиент из Новгорода оплатил «Моющий пылесос» в «СПб Невский» —
сидовом постамате без железа, который сайт продавал как ONLINE (город по
умолчанию — СПб). Через четыре часа деплой прогнал ``scripts.wipe_spb``:
постамат удалился вместе с бронью и платежом, деньги остались в ЮKassa
без записи у нас.

Теперь: wipe_spb в деплое нет, чистка постамата отказывается трогать
постамат с бронями или арендами, а сидовый постамат из бандла всегда
OFFLINE.
"""

import asyncio
import json
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from backend.core.database import Base
from backend.models.city import City
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    PaymentStatus,
    PaymentType,
    ReservationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.payment import Payment
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.reservation import Reservation
from backend.models.user import User
from scripts import apply_catalog_bundle
from scripts.migrate_lockers_to_real import (
    LockerHasOperationsError,
    _empty_locker_inventory,
    _purge_locker_contents,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _test_root() -> Path:
    root = Path.cwd() / ".tmp-catalog-sync-tests" / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root


def _sqlite_url(path: Path, *, async_driver: bool) -> str:
    prefix = "sqlite+aiosqlite:///" if async_driver else "sqlite:///"
    return prefix + path.resolve().as_posix()


class DeployScriptTests(unittest.TestCase):
    def test_deploy_does_not_run_wipe_spb(self):
        script = (REPO_ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        commands = [
            line for line in script.splitlines() if not line.strip().startswith("#")
        ]
        self.assertFalse(
            any("wipe_spb" in line for line in commands),
            "deploy.sh снова запускает wipe_spb — он удалял брони и платежи",
        )

    def test_bundle_sells_nothing_in_seed_lockers_and_puts_novgorod_first(self):
        bundle = json.loads(
            (REPO_ROOT / "deploy" / "catalog-sync.bundle.json").read_text(encoding="utf-8")
        )
        for locker in bundle["lockers"]:
            if locker["externalProvider"] == "seed":
                self.assertEqual(locker["status"], "OFFLINE", locker["externalLockerId"])

        active = sorted(
            (city for city in bundle["cities"] if city["isActive"]),
            key=lambda city: city["sortOrder"],
        )
        # Сайт без сохранённого города берёт первый — это должен быть
        # город, где постаматы настоящие.
        self.assertEqual(active[0]["slug"], "velikiy-novgorod")


class PurgeLockerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = _test_root()
        self.engine = create_async_engine(
            _sqlite_url(self.root / "purge.sqlite3", async_driver=True)
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.Session() as db:
            city = City(name="SPb", slug="spb", timezone="Europe/Moscow")
            category = ProductCategory(name="Cat", slug="cat", is_active=True, sort_order=0)
            db.add_all([city, category])
            await db.flush()
            self.locker = LockerLocation(
                city_id=city.id,
                name="SPb Nevsky",
                address="Nevsky 114",
                status=LockerStatus.ONLINE,
                external_provider="seed",
                external_locker_id="seed-spb-nevsky",
            )
            product = Product(category_id=category.id, name="Vacuum", slug="vacuum", is_active=True)
            db.add_all([self.locker, product])
            await db.flush()
            cell = LockerCell(
                locker_id=self.locker.id,
                label="M-C1",
                external_cell_id="M-C1",
                status=LockerCellStatus.OCCUPIED,
                supports_return=True,
            )
            db.add(cell)
            await db.flush()
            self.unit = InventoryUnit(
                product_id=product.id,
                locker_cell_id=cell.id,
                status=InventoryStatus.RESERVED,
                serial_number="SN-vacuum",
            )
            plan = PricePlan(
                product_id=product.id,
                name="1 day",
                duration_type="day",
                duration_value=1,
                base_amount=Decimal("790.00"),
                currency="RUB",
                is_active=True,
            )
            user = User(phone="+79990000119")
            db.add_all([self.unit, plan, user])
            await db.flush()
            self.product_id = product.id
            self.plan_id = plan.id
            self.user_id = user.id
            await db.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        shutil.rmtree(self.root, ignore_errors=True)

    async def _add_paid_booking(self) -> None:
        async with self.Session() as db:
            reservation = Reservation(
                user_id=self.user_id,
                product_id=self.product_id,
                inventory_unit_id=self.unit.id,
                locker_id=self.locker.id,
                price_plan_id=self.plan_id,
                status=ReservationStatus.CONFIRMED,
                duration_type="day",
                duration_value=1,
                quoted_amount=Decimal("790.00"),
                preauth_amount=Decimal("790.00"),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            )
            db.add(reservation)
            await db.flush()
            db.add(
                Payment(
                    user_id=self.user_id,
                    reservation_id=reservation.id,
                    provider="yookassa",
                    provider_payment_id="326d7e33-000f-5001-a000-142fa491aeed",
                    type=PaymentType.PREAUTH,
                    status=PaymentStatus.CAPTURED,
                    amount=Decimal("790.00"),
                    currency="RUB",
                )
            )
            await db.commit()

    async def _count(self, model) -> int:
        async with self.Session() as db:
            return int(await db.scalar(select(func.count()).select_from(model)))

    async def test_paid_booking_survives_the_wipe(self):
        await self._add_paid_booking()

        async with self.Session() as db:
            locker = await db.get(LockerLocation, self.locker.id)
            with self.assertRaises(LockerHasOperationsError):
                await _purge_locker_contents(db, locker)
            await db.rollback()

        self.assertEqual(await self._count(Reservation), 1)
        self.assertEqual(await self._count(Payment), 1)
        self.assertEqual(await self._count(LockerCell), 1)
        self.assertEqual(await self._count(InventoryUnit), 1)

    async def test_emptying_a_locker_with_bookings_is_refused(self):
        await self._add_paid_booking()

        async with self.Session() as db:
            changed, reason = await _empty_locker_inventory(
                db, provider="seed", external_id="seed-spb-nevsky"
            )
            await db.rollback()

        self.assertFalse(changed)
        self.assertIn("1 reservations", reason)
        self.assertEqual(await self._count(Payment), 1)

    async def test_locker_without_bookings_is_emptied(self):
        async with self.Session() as db:
            locker = await db.get(LockerLocation, self.locker.id)
            await _purge_locker_contents(db, locker)
            await db.commit()

        self.assertEqual(await self._count(LockerCell), 0)
        self.assertEqual(await self._count(InventoryUnit), 0)


class SeedLockerBundleTests(unittest.TestCase):
    def _bundle(self) -> dict:
        return {
            "categories": [{"slug": "cat", "name": "Cat", "sortOrder": 10, "isActive": True}],
            "mediaFiles": [],
            "products": [
                {
                    "slug": "vacuum",
                    "name": "Vacuum",
                    "brand": None,
                    "shortDescription": None,
                    "fullDescription": None,
                    "rulesText": None,
                    "kitDescription": None,
                    "specsJson": None,
                    "categorySlug": "cat",
                    "coverFileKey": None,
                    "galleryFileKeys": [],
                    "pricePlans": [
                        {
                            "name": "1 day",
                            "durationType": "day",
                            "durationValue": 1,
                            "baseAmount": "790.00",
                            "currency": "RUB",
                            "isActive": True,
                            "sortOrder": 10,
                        }
                    ],
                    "filter": None,
                    "isActive": True,
                }
            ],
            "cities": [
                {
                    "slug": "spb",
                    "name": "SPb",
                    "timezone": "Europe/Moscow",
                    "isActive": True,
                    "sortOrder": 10,
                }
            ],
            "lockers": [
                {
                    "citySlug": "spb",
                    "name": "SPb Nevsky",
                    "address": "Nevsky 114",
                    "lat": 59.93,
                    "lon": 30.36,
                    # Как в июне: бандл пересобрали из базы, где он ONLINE.
                    "status": "ONLINE",
                    "workingHoursJson": None,
                    "externalProvider": "seed",
                    "externalLockerId": "seed-spb-nevsky",
                    "partnerName": "Dev Seed",
                    "lastOnlineAt": None,
                }
            ],
            "cells": [
                {
                    "lockerExternalProvider": "seed",
                    "lockerExternalLockerId": "seed-spb-nevsky",
                    "externalCellId": None,
                    "label": "M-C1",
                    "size": "M",
                    "status": "OCCUPIED",
                    "supportsReturn": True,
                    "lastOpenedAt": None,
                    "lastClosedAt": None,
                    "lastEventAt": None,
                }
            ],
            "inventoryUnits": [
                {
                    "productSlug": "vacuum",
                    "lockerExternalProvider": "seed",
                    "lockerExternalLockerId": "seed-spb-nevsky",
                    "cellExternalCellId": None,
                    "cellLabel": "M-C1",
                    "serialNumber": None,
                    "barcode": None,
                    "status": "AVAILABLE",
                    "conditionGrade": None,
                    "conditionNote": None,
                    "purchasePrice": None,
                    "purchaseDate": None,
                    "lastCheckAt": None,
                }
            ],
            "managedProductSlugs": ["vacuum"],
        }

    def test_any_locker_without_esi_stays_offline(self):
        bundle = json.loads(json.dumps(self._bundle()).replace('"seed"', '"manual"'))
        root = _test_root()
        try:
            db_path = root / "target.sqlite3"
            apply_catalog_bundle._load_models()
            init_engine = create_engine(_sqlite_url(db_path, async_driver=False))
            Base.metadata.create_all(init_engine)
            init_engine.dispose()

            db_url = _sqlite_url(db_path, async_driver=False)
            with (
                patch.object(apply_catalog_bundle, "ROOT_DIR", root),
                patch.object(apply_catalog_bundle.settings, "DB_URL", db_url),
                patch.object(apply_catalog_bundle.settings, "ASYNC_DB_URL", db_url),
            ):
                apply_catalog_bundle.apply_bundle(
                    bundle, perform_apply=True, deactivate_missing=False, force=True
                )

            verify_engine = create_engine(db_url)
            with Session(verify_engine) as session:
                locker = session.scalars(select(LockerLocation)).one()
                self.assertEqual(locker.external_provider, "manual")
                self.assertEqual(locker.status, LockerStatus.OFFLINE)
            verify_engine.dispose()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_seed_locker_stays_offline_and_reapply_does_not_duplicate(self):
        root = _test_root()
        try:
            db_path = root / "target.sqlite3"
            apply_catalog_bundle._load_models()
            init_engine = create_engine(_sqlite_url(db_path, async_driver=False))
            Base.metadata.create_all(init_engine)
            init_engine.dispose()

            db_url = _sqlite_url(db_path, async_driver=False)
            with (
                patch.object(apply_catalog_bundle, "ROOT_DIR", root),
                patch.object(apply_catalog_bundle.settings, "DB_URL", db_url),
                patch.object(apply_catalog_bundle.settings, "ASYNC_DB_URL", db_url),
            ):
                # Два деплоя подряд, без wipe_spb между ними.
                for _ in range(2):
                    apply_catalog_bundle.apply_bundle(
                        self._bundle(),
                        perform_apply=True,
                        deactivate_missing=False,
                        force=True,
                    )

            verify_engine = create_engine(db_url)
            with Session(verify_engine) as session:
                lockers = session.scalars(select(LockerLocation)).all()
                self.assertEqual(len(lockers), 1)
                self.assertEqual(lockers[0].status, LockerStatus.OFFLINE)
                self.assertEqual(session.scalar(select(func.count()).select_from(LockerCell)), 1)
                self.assertEqual(session.scalar(select(func.count()).select_from(InventoryUnit)), 1)
            verify_engine.dispose()
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
