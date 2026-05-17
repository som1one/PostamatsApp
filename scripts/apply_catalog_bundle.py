from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.settings import settings
from backend.models.city import City
from backend.models.enums import InventoryStatus, LockerCellStatus, LockerStatus, MediaFileKind
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.media_file import MediaFile
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.product_filter import ProductFilter
from backend.models.product_image import ProductImage
from backend.utils.local_storage import store_local_upload
from backend.utils.products_utils import public_media_url
from backend.utils.uploads_utils import bucket_for_media_kind


DEFAULT_BUNDLE = ROOT_DIR / "deploy" / "catalog-sync.bundle.json"
MODEL_MODULES = (
    "backend.models.admin_account",
    "backend.models.admin_audit_event",
    "backend.models.admin_auth_session",
    "backend.models.admin_user",
    "backend.models.auth_session",
    "backend.models.auth_verification_session",
    "backend.models.city",
    "backend.models.condition_report",
    "backend.models.condition_report_photo",
    "backend.models.esi_event_log",
    "backend.models.featured_product_state",
    "backend.models.inventory_movement",
    "backend.models.inventory_unit",
    "backend.models.locker_cell",
    "backend.models.locker_location",
    "backend.models.media_file",
    "backend.models.payment",
    "backend.models.payment_event",
    "backend.models.price_plan",
    "backend.models.product",
    "backend.models.product_category",
    "backend.models.product_filter",
    "backend.models.product_image",
    "backend.models.rental",
    "backend.models.rental_event",
    "backend.models.reservation",
    "backend.models.return_request",
    "backend.models.user",
    "backend.models.verification_request",
)
SAFE_RESERVATION_STATUSES = {"expired", "cancelled"}
SAFE_RENTAL_STATUSES = {"completed", "cancelled"}
ASYNC_DB_URL_PREFIXES = (
    ("sqlite+aiosqlite://", "sqlite://"),
    ("postgresql+asyncpg://", "postgresql+psycopg2://"),
)


@dataclass
class SyncStats:
    categories_created: int = 0
    categories_updated: int = 0
    cities_created: int = 0
    cities_updated: int = 0
    lockers_created: int = 0
    lockers_updated: int = 0
    cells_created: int = 0
    cells_updated: int = 0
    media_copied: int = 0
    media_created: int = 0
    media_updated: int = 0
    products_created: int = 0
    products_updated: int = 0
    products_deactivated: int = 0
    plans_created: int = 0
    plans_updated: int = 0
    plans_deactivated: int = 0
    gallery_rows_replaced: int = 0
    filters_created: int = 0
    filters_updated: int = 0
    filters_deleted: int = 0
    units_created: int = 0
    units_updated: int = 0


def _load_models() -> None:
    for module_name in MODEL_MODULES:
        import_module(module_name)


def _normalize_sync_db_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    normalized = raw_url.strip()
    for async_prefix, sync_prefix in ASYNC_DB_URL_PREFIXES:
        if normalized.startswith(async_prefix):
            return sync_prefix + normalized[len(async_prefix) :]
    return normalized


def _effective_db_url() -> str:
    db_url = _normalize_sync_db_url(settings.DB_URL or settings.ASYNC_DB_URL)
    if db_url:
        return db_url
    return _db_url()


def _db_url() -> str:
    if not settings.DB_URL:
        raise RuntimeError("Задайте DB_URL для target database.")
    return settings.DB_URL


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_decimal(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return Decimal(text)


def _enum_value(enum_cls, raw: str | None):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    for member in enum_cls:
        if member.name.lower() == text.lower() or str(member.value).lower() == text.lower():
            return member
    raise ValueError(f"Неизвестное значение enum {enum_cls.__name__}: {raw}")


def _read_bundle(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _enum_text(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value).lower()
    return str(value).lower()


def _copy_media_if_needed(media_files: list[dict[str, Any]], stats: SyncStats) -> None:
    if settings.STORAGE_PROVIDER != "filesystem":
        print("Media copy skipped: STORAGE_PROVIDER != filesystem")
        return
    for item in media_files:
        src = ROOT_DIR / item["repoAssetPath"]
        if not src.exists():
            raise RuntimeError(f"Не найден asset из bundle: {src}")
        store_local_upload(item["fileKey"], src.read_bytes())
        stats.media_copied += 1


def _preflight_guard(session: Session, managed_slugs: set[str]) -> None:
    from backend.models.rental import Rental
    from backend.models.reservation import Reservation

    reservations = session.execute(
        select(Reservation.status, Product.slug)
        .join(Product, Product.id == Reservation.product_id)
        .where(Product.slug.in_(managed_slugs))
    ).all()
    risky_reservations = [row for row in reservations if _enum_text(row.status) not in SAFE_RESERVATION_STATUSES]
    if risky_reservations:
        raise RuntimeError(
            "В target DB есть активные/незавершённые reservations для переносимых товаров. "
            "Сначала завершите их или адаптируйте скрипт под вашу ситуацию."
        )

    rentals = session.execute(
        select(Rental.status, Product.slug)
        .join(InventoryUnit, InventoryUnit.id == Rental.inventory_unit_id)
        .join(Product, Product.id == InventoryUnit.product_id)
        .where(Product.slug.in_(managed_slugs))
    ).all()
    risky_rentals = [row for row in rentals if _enum_text(row.status) not in SAFE_RENTAL_STATUSES]
    if risky_rentals:
        raise RuntimeError(
            "В target DB есть активные/незавершённые rentals для переносимых товаров. "
            "Сначала завершите их или адаптируйте скрипт под вашу ситуацию."
        )


def _upsert_category(session: Session, payload: dict[str, Any], stats: SyncStats) -> ProductCategory:
    category = session.scalar(select(ProductCategory).where(ProductCategory.slug == payload["slug"]))
    if category is None:
        category = ProductCategory(
            name=payload["name"],
            slug=payload["slug"],
            sort_order=int(payload["sortOrder"]),
            is_active=bool(payload["isActive"]),
        )
        session.add(category)
        stats.categories_created += 1
        return category

    category.name = payload["name"]
    category.sort_order = int(payload["sortOrder"])
    category.is_active = bool(payload["isActive"])
    stats.categories_updated += 1
    return category


def _upsert_city(session: Session, payload: dict[str, Any], stats: SyncStats) -> City:
    city = session.scalar(select(City).where(City.slug == payload["slug"]))
    if city is None:
        city = City(
            name=payload["name"],
            slug=payload["slug"],
            timezone=payload["timezone"],
            is_active=bool(payload["isActive"]),
            sort_order=int(payload["sortOrder"]),
        )
        session.add(city)
        stats.cities_created += 1
        return city

    city.name = payload["name"]
    city.timezone = payload["timezone"]
    city.is_active = bool(payload["isActive"])
    city.sort_order = int(payload["sortOrder"])
    stats.cities_updated += 1
    return city


def _upsert_locker(
    session: Session,
    payload: dict[str, Any],
    city: City,
    stats: SyncStats,
) -> LockerLocation:
    stmt = select(LockerLocation).where(
        LockerLocation.external_provider == payload["externalProvider"],
        LockerLocation.external_locker_id == payload["externalLockerId"],
    )
    locker = session.scalar(stmt)
    if locker is None:
        locker = LockerLocation(
            city_id=city.id,
            name=payload["name"],
            address=payload["address"],
            lat=payload["lat"],
            lon=payload["lon"],
            status=_enum_value(LockerStatus, payload["status"]),
            working_hours_json=payload["workingHoursJson"],
            external_provider=payload["externalProvider"],
            external_locker_id=payload["externalLockerId"],
            partner_name=payload["partnerName"],
            last_online_at=_parse_datetime(payload["lastOnlineAt"]),
        )
        session.add(locker)
        stats.lockers_created += 1
        return locker

    locker.city_id = city.id
    locker.name = payload["name"]
    locker.address = payload["address"]
    locker.lat = payload["lat"]
    locker.lon = payload["lon"]
    locker.status = _enum_value(LockerStatus, payload["status"])
    locker.working_hours_json = payload["workingHoursJson"]
    locker.partner_name = payload["partnerName"]
    locker.last_online_at = _parse_datetime(payload["lastOnlineAt"])
    stats.lockers_updated += 1
    return locker


def _upsert_cell(
    session: Session,
    payload: dict[str, Any],
    locker: LockerLocation,
    stats: SyncStats,
) -> LockerCell:
    if payload["externalCellId"]:
        stmt = select(LockerCell).where(
            LockerCell.locker_id == locker.id,
            LockerCell.external_cell_id == payload["externalCellId"],
        )
    else:
        stmt = select(LockerCell).where(
            LockerCell.locker_id == locker.id,
            LockerCell.label == payload["label"],
        )
    cell = session.scalar(stmt)
    if cell is None:
        cell = LockerCell(
            locker_id=locker.id,
            external_cell_id=payload["externalCellId"],
            label=payload["label"],
            size=payload["size"],
            status=_enum_value(LockerCellStatus, payload["status"]),
            supports_return=bool(payload["supportsReturn"]),
            last_opened_at=_parse_datetime(payload["lastOpenedAt"]),
            last_closed_at=_parse_datetime(payload["lastClosedAt"]),
            last_event_at=_parse_datetime(payload["lastEventAt"]),
        )
        session.add(cell)
        stats.cells_created += 1
        return cell

    cell.external_cell_id = payload["externalCellId"]
    cell.label = payload["label"]
    cell.size = payload["size"]
    cell.status = _enum_value(LockerCellStatus, payload["status"])
    cell.supports_return = bool(payload["supportsReturn"])
    cell.last_opened_at = _parse_datetime(payload["lastOpenedAt"])
    cell.last_closed_at = _parse_datetime(payload["lastClosedAt"])
    cell.last_event_at = _parse_datetime(payload["lastEventAt"])
    stats.cells_updated += 1
    return cell


def _upsert_media_file(session: Session, payload: dict[str, Any], stats: SyncStats) -> MediaFile:
    media = session.scalar(select(MediaFile).where(MediaFile.file_key == payload["fileKey"]))
    kind = _enum_value(MediaFileKind, payload["kind"])
    if media is None:
        media = MediaFile(
            storage_provider="local",
            bucket=bucket_for_media_kind(kind),
            file_key=payload["fileKey"],
            mime_type=payload["mimeType"],
            file_size=int(payload["fileSize"]),
            original_name=payload["originalName"],
            kind=kind,
            uploaded_by_user_id=None,
            uploaded_by_admin_id=None,
            created_at=datetime.now(UTC),
        )
        session.add(media)
        stats.media_created += 1
        return media

    media.storage_provider = "local"
    media.bucket = bucket_for_media_kind(kind)
    media.mime_type = payload["mimeType"]
    media.file_size = int(payload["fileSize"])
    media.original_name = payload["originalName"]
    media.kind = kind
    stats.media_updated += 1
    return media


def _upsert_product(
    session: Session,
    payload: dict[str, Any],
    category: ProductCategory,
    cover_media: MediaFile | None,
    stats: SyncStats,
) -> Product:
    product = session.scalar(select(Product).where(Product.slug == payload["slug"]))
    if product is None:
        product = Product(
            category_id=category.id,
            name=payload["name"],
            slug=payload["slug"],
            short_description=payload["shortDescription"],
            full_description=payload["fullDescription"],
            specs_json=payload["specsJson"],
            rules_text=payload["rulesText"],
            kit_description=payload["kitDescription"],
            brand=payload["brand"],
            cover_file_id=cover_media.id if cover_media else None,
            is_active=bool(payload["isActive"]),
        )
        session.add(product)
        stats.products_created += 1
        return product

    product.category_id = category.id
    product.name = payload["name"]
    product.short_description = payload["shortDescription"]
    product.full_description = payload["fullDescription"]
    product.specs_json = payload["specsJson"]
    product.rules_text = payload["rulesText"]
    product.kit_description = payload["kitDescription"]
    product.brand = payload["brand"]
    product.cover_file_id = cover_media.id if cover_media else None
    product.is_active = bool(payload["isActive"])
    stats.products_updated += 1
    return product


def _sync_price_plans(
    session: Session,
    product: Product,
    plans: list[dict[str, Any]],
    stats: SyncStats,
) -> None:
    existing = {
        (item.duration_type, int(item.duration_value)): item
        for item in session.scalars(select(PricePlan).where(PricePlan.product_id == product.id)).all()
    }
    seen_keys: set[tuple[str, int]] = set()
    for payload in plans:
        key = (payload["durationType"], int(payload["durationValue"]))
        seen_keys.add(key)
        plan = existing.get(key)
        if plan is None:
            plan = PricePlan(
                product_id=product.id,
                name=payload["name"],
                duration_type=payload["durationType"],
                duration_value=int(payload["durationValue"]),
                base_amount=_parse_decimal(payload["baseAmount"]) or Decimal("0.00"),
                currency=payload["currency"],
                is_active=bool(payload["isActive"]),
                sort_order=int(payload["sortOrder"]),
            )
            session.add(plan)
            stats.plans_created += 1
            continue

        plan.name = payload["name"]
        plan.base_amount = _parse_decimal(payload["baseAmount"]) or Decimal("0.00")
        plan.currency = payload["currency"]
        plan.is_active = bool(payload["isActive"])
        plan.sort_order = int(payload["sortOrder"])
        stats.plans_updated += 1

    for key, plan in existing.items():
        if key not in seen_keys and plan.is_active:
            plan.is_active = False
            stats.plans_deactivated += 1


def _replace_product_gallery(
    session: Session,
    product: Product,
    gallery_media: list[MediaFile],
    stats: SyncStats,
) -> None:
    existing = session.scalars(select(ProductImage).where(ProductImage.product_id == product.id)).all()
    for item in existing:
        session.delete(item)
    for sort_order, media in enumerate(gallery_media):
        session.add(
            ProductImage(
                product_id=product.id,
                file_id=media.id,
                sort_order=sort_order,
            )
        )
    stats.gallery_rows_replaced += 1


def _sync_product_filter(
    session: Session,
    product: Product,
    payload: dict[str, Any] | None,
    stats: SyncStats,
) -> None:
    existing = session.scalar(select(ProductFilter).where(ProductFilter.product_id == product.id))
    if payload is None:
        if existing is not None:
            session.delete(existing)
            stats.filters_deleted += 1
        return

    cover_url = public_media_url(payload["coverFileKey"]) if payload.get("coverFileKey") else None
    gallery_urls = [
        public_media_url(file_key)
        for file_key in (payload.get("galleryFileKeys") or [])
        if public_media_url(file_key)
    ]

    if existing is None:
        session.add(
            ProductFilter(
                product_id=product.id,
                name=payload["name"],
                short_description=payload["shortDescription"],
                full_description=payload["fullDescription"],
                rules_text=payload["rulesText"],
                kit_description=payload["kitDescription"],
                cover_url=cover_url,
                gallery_urls_json=gallery_urls,
                price_plans_json=payload["pricePlans"] or [],
                is_active=bool(payload["isActive"]),
            )
        )
        stats.filters_created += 1
        return

    existing.name = payload["name"]
    existing.short_description = payload["shortDescription"]
    existing.full_description = payload["fullDescription"]
    existing.rules_text = payload["rulesText"]
    existing.kit_description = payload["kitDescription"]
    existing.cover_url = cover_url
    existing.gallery_urls_json = gallery_urls
    existing.price_plans_json = payload["pricePlans"] or []
    existing.is_active = bool(payload["isActive"])
    stats.filters_updated += 1


def _sync_inventory_units(
    session: Session,
    units: list[dict[str, Any]],
    products_by_slug: dict[str, Product],
    cells_by_key: dict[tuple[str | None, str | None, str | None, str | None], LockerCell],
    stats: SyncStats,
) -> None:
    for payload in units:
        cell_key = (
            payload["lockerExternalProvider"],
            payload["lockerExternalLockerId"],
            payload["cellExternalCellId"],
            payload["cellLabel"],
        )
        cell = cells_by_key[cell_key]
        product = products_by_slug[payload["productSlug"]]

        unit = None
        if payload["barcode"]:
            unit = session.scalar(select(InventoryUnit).where(InventoryUnit.barcode == payload["barcode"]))
        if unit is None and payload["serialNumber"]:
            unit = session.scalar(
                select(InventoryUnit).where(InventoryUnit.serial_number == payload["serialNumber"])
            )
        if unit is None:
            unit = session.scalar(select(InventoryUnit).where(InventoryUnit.locker_cell_id == cell.id))

        if unit is None:
            unit = InventoryUnit(
                product_id=product.id,
                locker_cell_id=cell.id,
                serial_number=payload["serialNumber"],
                barcode=payload["barcode"],
                status=_enum_value(InventoryStatus, payload["status"]),
                condition_grade=payload["conditionGrade"],
                condition_note=payload["conditionNote"],
                purchase_price=_parse_decimal(payload["purchasePrice"]),
                purchase_date=_parse_date(payload["purchaseDate"]),
                last_check_at=_parse_datetime(payload["lastCheckAt"]),
            )
            session.add(unit)
            stats.units_created += 1
            continue

        unit.product_id = product.id
        unit.locker_cell_id = cell.id
        unit.serial_number = payload["serialNumber"]
        unit.barcode = payload["barcode"]
        unit.status = _enum_value(InventoryStatus, payload["status"])
        unit.condition_grade = payload["conditionGrade"]
        unit.condition_note = payload["conditionNote"]
        unit.purchase_price = _parse_decimal(payload["purchasePrice"])
        unit.purchase_date = _parse_date(payload["purchaseDate"])
        unit.last_check_at = _parse_datetime(payload["lastCheckAt"])
        stats.units_updated += 1


def _deactivate_missing_products(
    session: Session,
    managed_slugs: set[str],
    stats: SyncStats,
) -> None:
    for product in session.scalars(select(Product).where(Product.slug.not_in(managed_slugs), Product.is_active.is_(True))).all():
        product.is_active = False
        stats.products_deactivated += 1


def _print_summary(stats: SyncStats) -> None:
    print("Catalog bundle sync summary:")
    for field_name in stats.__dataclass_fields__:
        print(f"  {field_name}: {getattr(stats, field_name)}")


def apply_bundle(
    bundle: dict[str, Any],
    *,
    perform_apply: bool,
    deactivate_missing: bool,
    force: bool,
) -> None:
    _load_models()
    engine = create_engine(_effective_db_url())
    stats = SyncStats()

    with Session(engine) as session:
        managed_slugs = set(bundle["managedProductSlugs"])
        if not force:
            _preflight_guard(session, managed_slugs)

        if perform_apply:
            _copy_media_if_needed(bundle["mediaFiles"], stats)

        categories_by_slug: dict[str, ProductCategory] = {}
        for payload in bundle["categories"]:
            categories_by_slug[payload["slug"]] = _upsert_category(session, payload, stats)
        session.flush()

        cities_by_slug: dict[str, City] = {}
        for payload in bundle["cities"]:
            cities_by_slug[payload["slug"]] = _upsert_city(session, payload, stats)
        session.flush()

        lockers_by_key: dict[tuple[str | None, str | None], LockerLocation] = {}
        for payload in bundle["lockers"]:
            city = cities_by_slug[payload["citySlug"]]
            locker = _upsert_locker(session, payload, city, stats)
            lockers_by_key[(payload["externalProvider"], payload["externalLockerId"])] = locker
        session.flush()

        cells_by_key: dict[tuple[str | None, str | None, str | None, str | None], LockerCell] = {}
        for payload in bundle["cells"]:
            locker = lockers_by_key[
                (payload["lockerExternalProvider"], payload["lockerExternalLockerId"])
            ]
            cell = _upsert_cell(session, payload, locker, stats)
            cells_by_key[
                (
                    payload["lockerExternalProvider"],
                    payload["lockerExternalLockerId"],
                    payload["externalCellId"],
                    payload["label"],
                )
            ] = cell
        session.flush()

        media_by_file_key: dict[str, MediaFile] = {}
        for payload in bundle["mediaFiles"]:
            media_by_file_key[payload["fileKey"]] = _upsert_media_file(session, payload, stats)
        session.flush()

        products_by_slug: dict[str, Product] = {}
        for payload in bundle["products"]:
            category = categories_by_slug[payload["categorySlug"]]
            cover_media = media_by_file_key.get(payload["coverFileKey"]) if payload.get("coverFileKey") else None
            product = _upsert_product(session, payload, category, cover_media, stats)
            products_by_slug[payload["slug"]] = product
        session.flush()

        for payload in bundle["products"]:
            product = products_by_slug[payload["slug"]]
            _sync_price_plans(session, product, payload["pricePlans"], stats)
            gallery_media = [
                media_by_file_key[file_key]
                for file_key in payload.get("galleryFileKeys") or []
                if file_key in media_by_file_key
            ]
            _replace_product_gallery(session, product, gallery_media, stats)
            _sync_product_filter(session, product, payload.get("filter"), stats)

        _sync_inventory_units(session, bundle["inventoryUnits"], products_by_slug, cells_by_key, stats)

        if deactivate_missing:
            _deactivate_missing_products(session, managed_slugs, stats)

        if perform_apply:
            session.commit()
        else:
            session.rollback()

    _print_summary(stats)
    if not perform_apply:
        print("Dry-run only. Re-run with --apply to persist changes.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Применяет bundle локального каталога к target DB и копирует изображения в runtime-uploads.",
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=DEFAULT_BUNDLE,
        help=f"Путь к bundle JSON (по умолчанию: {DEFAULT_BUNDLE})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Сохранить изменения в target DB. Без флага выполняется dry-run.",
    )
    parser.add_argument(
        "--deactivate-missing-products",
        action="store_true",
        help="Деактивировать товары, которых нет в bundle.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Пропустить preflight-проверку на активные rentals/reservations.",
    )
    args = parser.parse_args()

    bundle_path = args.bundle.resolve()
    if not bundle_path.exists():
        raise FileNotFoundError(f"Bundle file not found: {bundle_path}")

    bundle = _read_bundle(bundle_path)
    apply_bundle(
        bundle,
        perform_apply=bool(args.apply),
        deactivate_missing=bool(args.deactivate_missing_products),
        force=bool(args.force),
    )


if __name__ == "__main__":
    main()
