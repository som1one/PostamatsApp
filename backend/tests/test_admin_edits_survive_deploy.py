"""Правки из админки переживают выкладку.

Каждая выкладка накатывает каталог (``scripts/apply_catalog_bundle.py``).
Раньше он молча затирал то, что оператор поправил в админке: тексты,
активность товара, настройки города, а городские фильтры товаров удалял.
Теперь поля, которые в админке действительно поменяли, выкладка не
трогает, а остальные — обновляет из каталога как прежде.
"""

from __future__ import annotations

import copy
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

TEST_ROOT = Path.cwd() / ".tmp-catalog-sync-tests" / uuid4().hex
TEST_ROOT.mkdir(parents=True, exist_ok=True)
TEST_DB_URL = "sqlite+aiosqlite:///" + (TEST_ROOT / "db.sqlite3").resolve().as_posix()
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL

from backend.main import app  # noqa: E402,F401
from backend.core.database import Base, SessionLocal, engine  # noqa: E402
from backend.models.admin_account import AdminAccount  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import AdminRole  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_filter import ProductFilter  # noqa: E402
from backend.routers.admin import cities as admin_cities  # noqa: E402
from backend.routers.admin import product_filters as admin_filters  # noqa: E402
from backend.routers.admin import products as admin_products  # noqa: E402
from backend.schemas.admin_panel_schemas import (  # noqa: E402
    AdminUpdateCityPayload,
    AdminUpdateProductPayload,
)
from backend.schemas.product_filter_schemas import AdminCreateProductFilterPayload  # noqa: E402
from backend.utils.admin_auth_utils import hash_password  # noqa: E402
from scripts import apply_catalog_bundle  # noqa: E402

SYNC_DB_URL = "sqlite:///" + (TEST_ROOT / "db.sqlite3").resolve().as_posix()

BUNDLE = {
    "categories": [{"slug": "cat", "name": "Cat", "sortOrder": 10, "isActive": True}],
    "mediaFiles": [],
    "products": [
        {
            "slug": "vacuum",
            "name": "Vacuum",
            "brand": "Karcher",
            "shortDescription": "Short",
            "fullDescription": "Bundle text",
            "rulesText": None,
            "kitDescription": "Hose",
            "specsJson": None,
            "categorySlug": "cat",
            "coverFileKey": None,
            "galleryFileKeys": [],
            "pricePlans": [
                {
                    "name": "1 day", "durationType": "day", "durationValue": 1,
                    "baseAmount": "790.00", "currency": "RUB", "isActive": True, "sortOrder": 10,
                }
            ],
            "filter": None,
            "isActive": True,
        }
    ],
    "cities": [
        {"slug": "vn", "name": "Novgorod", "timezone": "Europe/Moscow", "isActive": True, "sortOrder": 5}
    ],
    "lockers": [],
    "cells": [],
    "inventoryUnits": [],
    "managedProductSlugs": ["vacuum"],
}


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PATCH",
            "headers": [(b"user-agent", b"pytest")],
            "path": "/api/admin/x",
            "client": ("127.0.0.1", 0),
        }
    )


def _deploy(bundle: dict) -> apply_catalog_bundle.SyncStats:
    """То, что делает выкладка: накатывает каталог на базу."""
    with (
        patch.object(apply_catalog_bundle, "ROOT_DIR", TEST_ROOT),
        patch.object(apply_catalog_bundle.settings, "DB_URL", SYNC_DB_URL),
        patch.object(apply_catalog_bundle.settings, "ASYNC_DB_URL", SYNC_DB_URL),
        patch.object(apply_catalog_bundle, "_print_summary") as summary,
    ):
        apply_catalog_bundle.apply_bundle(
            bundle, perform_apply=True, deactivate_missing=False, force=True
        )
    return summary.call_args.args[0]


def _read(model, **where):
    sync_engine = create_engine(SYNC_DB_URL)
    try:
        with Session(sync_engine) as session:
            stmt = select(model)
            for key, value in where.items():
                stmt = stmt.where(getattr(model, key) == value)
            return session.scalars(stmt).first()
    finally:
        sync_engine.dispose()


class AdminEditsSurviveDeployTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            admin = AdminAccount(
                name="Root", login="root", role=AdminRole.SUPER_ADMIN,
                password_hash=hash_password("irrelevant"),
            )
            db.add(admin)
            await db.commit()
            self.admin_id = admin.id
        _deploy(BUNDLE)

        async def fake_get_current_admin(request, db):
            return await db.get(AdminAccount, self.admin_id), None

        self.patches = [
            patch.object(admin_products, "get_current_admin", new=fake_get_current_admin),
            patch.object(admin_cities, "get_current_admin", new=fake_get_current_admin),
            patch.object(admin_filters, "_require_admin_or_403", new=fake_get_current_admin),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_ROOT, ignore_errors=True)

    async def _edit_product_like_the_admin_form(self, **changes) -> Product:
        """Форма товара отправляет все поля разом — меняем только часть."""
        product = _read(Product, slug="vacuum")
        body = {
            "categoryId": product.category_id,
            "name": product.name,
            "slug": product.slug,
            "shortDescription": product.short_description,
            "fullDescription": product.full_description,
            "rulesText": product.rules_text,
            "kitDescription": product.kit_description,
            "brand": product.brand,
            "isActive": product.is_active,
            "specsJson": product.specs_json,
            "coverFileId": product.cover_file_id,
            "galleryFileIds": [],
        }
        body.update(changes)
        async with SessionLocal() as db:
            await admin_products.update_admin_product(
                _request(), product.id, AdminUpdateProductPayload(**body), db
            )
        return _read(Product, slug=body["slug"])

    async def test_fields_edited_in_admin_survive_the_next_deploy(self):
        edited = await self._edit_product_like_the_admin_form(
            fullDescription="Operator text", isActive=False
        )
        # Отмечены только реально изменённые поля, не все из формы.
        self.assertEqual(edited.admin_edited_fields, ["fullDescription", "isActive"])

        bundle = copy.deepcopy(BUNDLE)
        bundle["products"][0].update(
            name="Vacuum 2", fullDescription="Bundle text 2", kitDescription="Hose, brush"
        )
        stats = _deploy(bundle)

        product = _read(Product, slug="vacuum")
        self.assertEqual(product.full_description, "Operator text")
        self.assertFalse(product.is_active)
        # Чего в админке не трогали — по-прежнему из каталога.
        self.assertEqual(product.name, "Vacuum 2")
        self.assertEqual(product.kit_description, "Hose, brush")
        self.assertEqual(stats.admin_edits_kept, ["product vacuum: fullDescription, isActive"])

    async def test_catalog_product_keeps_its_slug(self):
        with patch.object(admin_products, "is_catalog_product", new=lambda slug: slug == "vacuum"):
            with self.assertRaises(HTTPException) as ctx:
                await self._edit_product_like_the_admin_form(slug="vacuum-new")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIsNotNone(_read(Product, slug="vacuum"))

    async def test_city_settings_edited_in_admin_survive_the_next_deploy(self):
        city = _read(City, slug="vn")
        async with SessionLocal() as db:
            await admin_cities.update_admin_city(
                _request(), city.id, AdminUpdateCityPayload(isActive=False, name=city.name), db
            )
        bundle = copy.deepcopy(BUNDLE)
        bundle["cities"][0]["name"] = "Veliky Novgorod"
        _deploy(bundle)

        city = _read(City, slug="vn")
        self.assertFalse(city.is_active)
        self.assertEqual(city.name, "Veliky Novgorod")
        self.assertEqual(city.admin_edited_fields, ["isActive"])

    async def test_filter_created_in_admin_is_not_deleted_by_the_deploy(self):
        product = _read(Product, slug="vacuum")
        async with SessionLocal() as db:
            await admin_filters.create_product_filter(
                _request(),
                AdminCreateProductFilterPayload(productId=product.id, name="Только в Новгороде"),
                db,
            )
        _deploy(BUNDLE)

        product_filter = _read(ProductFilter, product_id=product.id)
        self.assertIsNotNone(product_filter)
        self.assertEqual(product_filter.name, "Только в Новгороде")


if __name__ == "__main__":
    unittest.main()
