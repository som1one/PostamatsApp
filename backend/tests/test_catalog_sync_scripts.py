import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.core.database import Base
from backend.models.inventory_unit import InventoryUnit
from backend.models.media_file import MediaFile
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from scripts import apply_catalog_bundle, export_catalog_bundle


def _sqlite_url(path: Path, *, async_driver: bool) -> str:
    prefix = "sqlite+aiosqlite:///" if async_driver else "sqlite:///"
    return prefix + path.resolve().as_posix()


def _workspace_test_root() -> Path:
    root = Path.cwd() / ".tmp-catalog-sync-tests" / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root


class CatalogSyncScriptTests(unittest.TestCase):
    def test_build_bundle_includes_filter_assets_without_media_rows(self):
        root = _workspace_test_root()
        try:
            source_db = root / "backend" / "dev.sqlite3"
            source_db.parent.mkdir(parents=True, exist_ok=True)
            assets_dir = root / "assets" / "uploads" / "items"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "filter-cover.jpg").write_bytes(b"cover")
            (assets_dir / "filter-gallery.jpg").write_bytes(b"gallery")

            conn = sqlite3.connect(source_db)
            conn.executescript(
                """
                create table product_categories (
                    id text primary key,
                    slug text not null,
                    name text not null,
                    sort_order integer not null,
                    is_active integer not null
                );
                create table products (
                    id text primary key,
                    category_id text not null,
                    name text not null,
                    slug text not null,
                    short_description text,
                    full_description text,
                    specs_json text,
                    rules_text text,
                    kit_description text,
                    brand text,
                    cover_file_id text,
                    is_active integer not null
                );
                create table price_plans (
                    product_id text not null,
                    name text not null,
                    duration_type text not null,
                    duration_value integer not null,
                    base_amount text not null,
                    currency text not null,
                    is_active integer not null,
                    sort_order integer not null
                );
                create table product_images (
                    product_id text not null,
                    file_id text not null,
                    sort_order integer not null,
                    created_at text
                );
                create table product_filters (
                    product_id text not null,
                    name text,
                    short_description text,
                    full_description text,
                    rules_text text,
                    kit_description text,
                    cover_url text,
                    gallery_urls_json text,
                    price_plans_json text,
                    is_active integer not null
                );
                create table media_files (
                    id text primary key,
                    storage_provider text,
                    bucket text,
                    file_key text,
                    mime_type text,
                    file_size integer,
                    original_name text,
                    kind text
                );
                create table cities (
                    id text primary key,
                    slug text not null,
                    name text not null,
                    timezone text not null,
                    is_active integer not null,
                    sort_order integer not null
                );
                create table locker_locations (
                    id text primary key,
                    city_id text not null,
                    name text not null,
                    address text not null,
                    lat real,
                    lon real,
                    status text not null,
                    working_hours_json text,
                    external_provider text,
                    external_locker_id text,
                    partner_name text,
                    last_online_at text
                );
                create table locker_cells (
                    id text primary key,
                    locker_id text not null,
                    external_cell_id text,
                    label text,
                    size text,
                    status text not null,
                    supports_return integer not null,
                    last_opened_at text,
                    last_closed_at text,
                    last_event_at text
                );
                create table inventory_units (
                    id text primary key,
                    product_id text not null,
                    locker_cell_id text,
                    serial_number text,
                    barcode text,
                    status text not null,
                    condition_grade text,
                    condition_note text,
                    purchase_price text,
                    purchase_date text,
                    last_check_at text
                );
                """
            )
            conn.execute(
                "insert into product_categories (id, slug, name, sort_order, is_active) values (?, ?, ?, ?, ?)",
                ("cat-1", "projectors", "Projectors", 10, 1),
            )
            conn.execute(
                """
                insert into products (
                    id, category_id, name, slug, short_description, full_description,
                    specs_json, rules_text, kit_description, brand, cover_file_id, is_active
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "prod-1",
                    "cat-1",
                    "Portable Projector",
                    "portable-projector",
                    "Short",
                    "Full",
                    json.dumps({"power": "100W"}),
                    "Rules",
                    "Kit",
                    "Acme",
                    None,
                    1,
                ),
            )
            conn.execute(
                """
                insert into price_plans (
                    product_id, name, duration_type, duration_value, base_amount, currency, is_active, sort_order
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("prod-1", "1 day", "day", 1, "1590.00", "RUB", 1, 10),
            )
            conn.execute(
                """
                insert into product_filters (
                    product_id, name, short_description, full_description, rules_text, kit_description,
                    cover_url, gallery_urls_json, price_plans_json, is_active
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "prod-1",
                    "Portable Projector Promo",
                    "Promo short",
                    "Promo full",
                    "Promo rules",
                    "Promo kit",
                    "https://example.com/assets/uploads/items/filter-cover.jpg",
                    json.dumps(
                        [
                            "https://example.com/assets/uploads/items/filter-gallery.jpg",
                        ]
                    ),
                    json.dumps([]),
                    1,
                ),
            )
            conn.execute(
                "insert into cities (id, slug, name, timezone, is_active, sort_order) values (?, ?, ?, ?, ?, ?)",
                ("city-1", "spb", "Saint Petersburg", "Europe/Moscow", 1, 10),
            )
            conn.execute(
                """
                insert into locker_locations (
                    id, city_id, name, address, lat, lon, status, working_hours_json,
                    external_provider, external_locker_id, partner_name, last_online_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "locker-1",
                    "city-1",
                    "Locker 1",
                    "Main street",
                    59.93,
                    30.36,
                    "online",
                    json.dumps({"mode": "daily"}),
                    "seed",
                    "LOCKER-1",
                    "Seed",
                    None,
                ),
            )
            conn.execute(
                """
                insert into locker_cells (
                    id, locker_id, external_cell_id, label, size, status,
                    supports_return, last_opened_at, last_closed_at, last_event_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("cell-1", "locker-1", "A1", "A1", "M", "occupied", 1, None, None, None),
            )
            conn.execute(
                """
                insert into inventory_units (
                    id, product_id, locker_cell_id, serial_number, barcode, status,
                    condition_grade, condition_note, purchase_price, purchase_date, last_check_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "unit-1",
                    "prod-1",
                    "cell-1",
                    "SERIAL-1",
                    "BARCODE-1",
                    "available",
                    "A",
                    "Ready",
                    "1000.00",
                    "2026-01-01",
                    None,
                ),
            )
            conn.commit()
            conn.close()

            with patch.object(export_catalog_bundle, "ROOT_DIR", root):
                bundle = export_catalog_bundle.build_bundle(
                    source_db=source_db,
                    excluded_prefixes=(),
                )

            media_by_key = {item["fileKey"]: item for item in bundle["mediaFiles"]}
            self.assertEqual(
                set(media_by_key),
                {
                    "uploads/items/filter-cover.jpg",
                    "uploads/items/filter-gallery.jpg",
                },
            )
            self.assertEqual(media_by_key["uploads/items/filter-cover.jpg"]["kind"], "product_cover")
            self.assertEqual(media_by_key["uploads/items/filter-gallery.jpg"]["kind"], "product_gallery")
            self.assertEqual(bundle["products"][0]["filter"]["coverFileKey"], "uploads/items/filter-cover.jpg")
            self.assertEqual(
                bundle["products"][0]["filter"]["galleryFileKeys"],
                ["uploads/items/filter-gallery.jpg"],
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_apply_bundle_works_with_async_style_db_url(self):
        root = _workspace_test_root()
        try:
            db_path = root / "backend" / "target.sqlite3"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            asset_path = root / "assets" / "uploads" / "items" / "portable-projector-cover.jpg"
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            asset_path.write_bytes(b"portable-projector-cover")
            runtime_upload_root = root / "runtime-uploads"

            apply_catalog_bundle._load_models()
            init_engine = create_engine(_sqlite_url(db_path, async_driver=False))
            Base.metadata.create_all(init_engine)
            init_engine.dispose()

            bundle = {
                "categories": [
                    {
                        "slug": "projectors",
                        "name": "Projectors",
                        "sortOrder": 10,
                        "isActive": True,
                    }
                ],
                "mediaFiles": [
                    {
                        "fileKey": "uploads/items/portable-projector-cover.jpg",
                        "mimeType": "image/jpeg",
                        "fileSize": len(b"portable-projector-cover"),
                        "originalName": "portable-projector-cover.jpg",
                        "kind": "product_cover",
                        "repoAssetPath": "assets/uploads/items/portable-projector-cover.jpg",
                    }
                ],
                "products": [
                    {
                        "slug": "portable-projector",
                        "name": "Portable Projector",
                        "brand": "Acme",
                        "shortDescription": "Short",
                        "fullDescription": "Full",
                        "rulesText": "Rules",
                        "kitDescription": "Kit",
                        "specsJson": {"power": "100W"},
                        "categorySlug": "projectors",
                        "coverFileKey": "uploads/items/portable-projector-cover.jpg",
                        "galleryFileKeys": [],
                        "pricePlans": [
                            {
                                "name": "1 day",
                                "durationType": "day",
                                "durationValue": 1,
                                "baseAmount": "1590.00",
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
                        "name": "Saint Petersburg",
                        "timezone": "Europe/Moscow",
                        "isActive": True,
                        "sortOrder": 10,
                    }
                ],
                "lockers": [
                    {
                        "citySlug": "spb",
                        "name": "Locker 1",
                        "address": "Main street",
                        "lat": 59.93,
                        "lon": 30.36,
                        "status": "online",
                        "workingHoursJson": {"mode": "daily"},
                        "externalProvider": "seed",
                        "externalLockerId": "LOCKER-1",
                        "partnerName": "Seed",
                        "lastOnlineAt": None,
                    }
                ],
                "cells": [
                    {
                        "lockerExternalProvider": "seed",
                        "lockerExternalLockerId": "LOCKER-1",
                        "externalCellId": "A1",
                        "label": "A1",
                        "size": "M",
                        "status": "occupied",
                        "supportsReturn": True,
                        "lastOpenedAt": None,
                        "lastClosedAt": None,
                        "lastEventAt": None,
                    }
                ],
                "inventoryUnits": [
                    {
                        "productSlug": "portable-projector",
                        "lockerExternalProvider": "seed",
                        "lockerExternalLockerId": "LOCKER-1",
                        "cellExternalCellId": "A1",
                        "cellLabel": "A1",
                        "serialNumber": "SERIAL-1",
                        "barcode": "BARCODE-1",
                        "status": "available",
                        "conditionGrade": "A",
                        "conditionNote": "Ready",
                        "purchasePrice": "1000.00",
                        "purchaseDate": "2026-01-01",
                        "lastCheckAt": None,
                    }
                ],
                "managedProductSlugs": ["portable-projector"],
            }

            async_db_url = _sqlite_url(db_path, async_driver=True)
            with (
                patch.object(apply_catalog_bundle, "ROOT_DIR", root),
                patch.object(apply_catalog_bundle.settings, "DB_URL", async_db_url),
                patch.object(apply_catalog_bundle.settings, "ASYNC_DB_URL", async_db_url),
                patch.object(apply_catalog_bundle.settings, "UPLOAD_DEV_STUB", False),
                patch.object(apply_catalog_bundle.settings, "STORAGE_PROVIDER", "filesystem"),
                patch.object(apply_catalog_bundle.settings, "LOCAL_UPLOAD_ROOT", str(runtime_upload_root)),
                patch.object(apply_catalog_bundle.settings, "MEDIA_PUBLIC_BASE_URL", ""),
            ):
                apply_catalog_bundle.apply_bundle(
                    bundle,
                    perform_apply=True,
                    deactivate_missing=False,
                    force=False,
                )

            verify_engine = create_engine(_sqlite_url(db_path, async_driver=False))
            with Session(verify_engine) as session:
                product = session.scalar(select(Product).where(Product.slug == "portable-projector"))
                self.assertIsNotNone(product)

                media = session.scalar(
                    select(MediaFile).where(MediaFile.file_key == "uploads/items/portable-projector-cover.jpg")
                )
                self.assertIsNotNone(media)
                self.assertEqual(product.cover_file_id, media.id)

                plan = session.scalar(select(PricePlan).where(PricePlan.product_id == product.id))
                self.assertIsNotNone(plan)

                unit = session.scalar(select(InventoryUnit).where(InventoryUnit.product_id == product.id))
                self.assertIsNotNone(unit)
                self.assertEqual(unit.barcode, "BARCODE-1")
            verify_engine.dispose()

            uploaded_copy = runtime_upload_root / "uploads" / "items" / "portable-projector-cover.jpg"
            self.assertTrue(uploaded_copy.exists())
            self.assertEqual(uploaded_copy.read_bytes(), b"portable-projector-cover")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
