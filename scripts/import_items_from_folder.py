"""Импорт товаров из папки `items/` в БД и постаматы.

Каждая подпапка `items/<имя>/` — отдельный товар. В подпапке должны
быть:

- одна или несколько картинок ``*.webp`` / ``*.jpg`` / ``*.png`` —
  первая по алфавиту становится cover, остальные идут в галерею.
- текстовый файл с ценой за сутки. Имя файла произвольное (`.txt` /
  `Текстовый документ.txt` и т.п.). Содержимое — строка вида
  ``От 900 сутки``, ``1. От 1000 сутки`` или просто число. Скрипт
  выдёргивает первое целое число.

Для каждого товара:

1. Создаётся ``Product`` (категория ``home``, ``is_active=True``).
2. Картинки кладутся в LOCAL_UPLOAD_ROOT через ``store_local_upload``,
   создаются ``MediaFile`` с ``kind=PRODUCT_COVER/PRODUCT_GALLERY``.
3. Создаются ``PricePlan`` 1/2/3/7 дней с прогрессивной скидкой
   (та же таблица, что в ``backend/scripts/add_extra_price_plans.py``).
4. Кладётся по 1 единице ``InventoryUnit`` в каждый из трёх
   постаматов: СПб Невский, ВН Центр, ВН Запад. Если у постамата
   нет свободной ``OCCUPIED``-ячейки — создаётся новая.

Скрипт идемпотентный: повторный запуск проверяет, что у каждого
товара уже есть нужные сущности, и ничего не дублирует.

Запуск (на VPS, внутри backend-контейнера):

    docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml \\
        exec backend python -m scripts.import_items_from_folder \\
        --items-dir /app/items
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.core.database import SessionLocal, engine  # noqa: E402
from backend.core.settings import settings  # noqa: E402
from backend.models.enums import (  # noqa: E402
    InventoryStatus,
    LockerCellStatus,
    MediaFileKind,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.media_file import MediaFile  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.product_image import ProductImage  # noqa: E402
from backend.utils.local_storage import store_local_upload  # noqa: E402

# Подгружаем все модели целиком — иначе SQLAlchemy не построит граф
# таблиц и упадёт на flush с NoReferencedTableError.
from backend.models import (  # noqa: E402, F401
    admin_account,
    admin_audit_event,
    admin_auth_session,
    admin_user,
    auth_session,
    auth_verification_session,
    city,
    condition_report,
    condition_report_photo,
    esi_event_log,
    inventory_movement,
    payment,
    payment_event,
    rental,
    rental_event,
    rental_idea,
    return_request,
    reservation,
    user,
    verification_request,
)


logger = logging.getLogger("import_items")


# Постаматы, в которые мы расселяем новые товары.
TARGET_LOCKERS: tuple[tuple[str, str], ...] = (
    ("seed", "seed-spb-nevsky"),
    ("esi", "PST_0980"),
    ("seed", "seed-vn-west"),
)


# Категория по умолчанию для всех импортируемых товаров.
DEFAULT_CATEGORY_SLUG = "home"


@dataclass
class ItemImport:
    folder: Path
    name: str
    slug: str
    cover: Path
    gallery: list[Path]
    base_price_rub: Decimal


_SLUG_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def _slugify(name: str) -> str:
    """Латинизирует и нормализует имя в slug."""
    text = name.strip().lower()
    text = text.translate(_SLUG_TRANSLIT)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "item"


def _parse_price(text: str) -> Decimal:
    """Извлекает первое целое число из строки и возвращает как Decimal."""
    match = re.search(r"\d+", text)
    if not match:
        raise ValueError(f"price not found in: {text!r}")
    return Decimal(match.group(0))


def _read_price_file(folder: Path) -> Decimal:
    txt_files = sorted(folder.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"no .txt with price found in {folder}")
    raw = txt_files[0].read_bytes()
    # Файлы из Windows иногда в cp1251. Пробуем utf-8, потом cp1251.
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"cannot decode {txt_files[0]}")
    return _parse_price(text)


_IMAGE_EXTS = {".webp", ".jpg", ".jpeg", ".png"}


def _collect_images(folder: Path) -> list[Path]:
    images = [p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_EXTS]
    if not images:
        raise FileNotFoundError(f"no images found in {folder}")
    # Самый «тяжёлый» файл обычно и есть фотография товара, а промо-
    # баннеры/превью весят меньше. Сортируем по убыванию размера, при
    # равенстве — по имени, чтобы порядок был детерминирован.
    images.sort(key=lambda p: (-p.stat().st_size, p.name))
    return images


def _scan_items_dir(items_dir: Path) -> list[ItemImport]:
    if not items_dir.exists():
        raise FileNotFoundError(f"items dir not found: {items_dir}")
    items: list[ItemImport] = []
    for entry in sorted(items_dir.iterdir()):
        if not entry.is_dir():
            continue
        try:
            images = _collect_images(entry)
            price = _read_price_file(entry)
        except FileNotFoundError as exc:
            logger.warning("[skip] %s: %s", entry.name, exc)
            continue
        items.append(
            ItemImport(
                folder=entry,
                name=entry.name,
                slug=_slugify(entry.name),
                cover=images[0],
                gallery=images[1:],
                base_price_rub=price,
            )
        )
    return items


# Прогрессивная скидка — та же, что в backend/scripts/add_extra_price_plans.py.
def _discount_percent(days: int) -> int:
    if days <= 0 or days == 1:
        return 0
    if days == 2:
        return 10
    if days == 3:
        return 15
    return min(60, 15 + (days - 3) * 3)


def _round_to_10_rub(amount: Decimal) -> Decimal:
    quantum = Decimal("10")
    return (amount / quantum).quantize(Decimal("1")) * quantum


def _build_price_plans(base_per_day: Decimal) -> list[tuple[str, str, int, Decimal, int]]:
    """Возвращает список (name, duration_type, duration_value, amount, sort_order)."""
    plans: list[tuple[str, str, int, Decimal, int]] = []
    for sort_order, days in enumerate((1, 2, 3, 7), start=1):
        percent = _discount_percent(days)
        amount = _round_to_10_rub(base_per_day * Decimal(days) * (Decimal(100 - percent) / Decimal(100)))
        plans.append((
            f"{days} {'день' if days == 1 else 'дня' if days < 5 else 'дней'}",
            "day",
            days,
            amount,
            sort_order,
        ))
    return plans


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(ext, "application/octet-stream")


def _build_file_key(slug: str, original_name: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", original_name).strip("-._") or "file"
    return f"product/{slug}/{uuid4()}-{safe_name}"


async def _ensure_category(session: AsyncSession, slug: str) -> ProductCategory:
    cat = (
        await session.scalars(select(ProductCategory).where(ProductCategory.slug == slug))
    ).first()
    if cat is None:
        # Создаём базовую категорию, если её нет.
        cat = ProductCategory(
            id=uuid4(),
            slug=slug,
            name="Для дома",
            sort_order=50,
            is_active=True,
        )
        session.add(cat)
        await session.flush()
    return cat


async def _create_or_update_product(
    session: AsyncSession,
    *,
    category_id: UUID,
    item: ItemImport,
) -> tuple[Product, bool]:
    """Возвращает (product, created)."""
    product = (
        await session.scalars(select(Product).where(Product.slug == item.slug))
    ).first()
    if product is not None:
        return product, False
    product = Product(
        id=uuid4(),
        category_id=category_id,
        name=item.name,
        slug=item.slug,
        short_description=None,
        full_description=None,
        kit_description=None,
        rules_text=None,
        brand=None,
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product, True


async def _import_media(
    session: AsyncSession,
    *,
    image_path: Path,
    slug: str,
    kind: MediaFileKind,
) -> MediaFile:
    body = image_path.read_bytes()
    file_key = _build_file_key(slug, image_path.name)
    store_local_upload(file_key, body)
    media = MediaFile(
        id=uuid4(),
        storage_provider=settings.STORAGE_PROVIDER or "filesystem",
        bucket="filesystem-public",
        file_key=file_key,
        mime_type=_mime_for(image_path),
        file_size=len(body),
        original_name=image_path.name,
        kind=kind,
        uploaded_by_user_id=None,
        uploaded_by_admin_id=None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(media)
    await session.flush()
    return media


async def _ensure_product_images(
    session: AsyncSession,
    *,
    product: Product,
    item: ItemImport,
    reset: bool = False,
) -> None:
    if reset:
        # Сносим текущую обложку и всю галерею — потом перезальём.
        # Порядок важен из-за FK product_images.file_id → media_files.id
        # и products.cover_file_id → media_files.id: сначала отвязываем
        # cover и удаляем строки product_images, делаем flush, и только
        # потом удаляем сами MediaFile.
        media_ids_to_delete: list[UUID] = []
        if product.cover_file_id is not None:
            media_ids_to_delete.append(product.cover_file_id)
            product.cover_file_id = None
        existing_images = (
            await session.scalars(
                select(ProductImage).where(ProductImage.product_id == product.id)
            )
        ).all()
        for image in existing_images:
            media_ids_to_delete.append(image.file_id)
            await session.delete(image)
        # Flush — чтобы UPDATE products.cover_file_id=NULL и DELETE
        # FROM product_images ушли в БД до того, как мы попытаемся
        # удалить MediaFile.
        await session.flush()
        for media_id in media_ids_to_delete:
            old_media = await session.get(MediaFile, media_id)
            if old_media is not None:
                await session.delete(old_media)
        await session.flush()
    # Cover
    if product.cover_file_id is None:
        cover_media = await _import_media(
            session, image_path=item.cover, slug=item.slug, kind=MediaFileKind.PRODUCT_COVER
        )
        product.cover_file_id = cover_media.id
    # Gallery
    existing = (
        await session.scalars(
            select(ProductImage).where(ProductImage.product_id == product.id)
        )
    ).all()
    if existing:
        return  # галерея уже есть — повторно не импортируем
    for index, gallery_image in enumerate(item.gallery, start=1):
        media = await _import_media(
            session, image_path=gallery_image, slug=item.slug, kind=MediaFileKind.PRODUCT_GALLERY
        )
        session.add(
            ProductImage(
                id=uuid4(),
                product_id=product.id,
                file_id=media.id,
                sort_order=index,
            )
        )


async def _ensure_price_plans(
    session: AsyncSession,
    *,
    product: Product,
    item: ItemImport,
) -> None:
    existing = {
        (plan.duration_type, plan.duration_value)
        for plan in (
            await session.scalars(select(PricePlan).where(PricePlan.product_id == product.id))
        ).all()
    }
    for name, duration_type, duration_value, amount, sort_order in _build_price_plans(
        item.base_price_rub
    ):
        if (duration_type, duration_value) in existing:
            continue
        session.add(
            PricePlan(
                id=uuid4(),
                product_id=product.id,
                name=name,
                duration_type=duration_type,
                duration_value=duration_value,
                base_amount=amount,
                currency="RUB",
                is_active=True,
                sort_order=sort_order,
            )
        )


async def _place_in_locker(
    session: AsyncSession,
    *,
    product: Product,
    locker: LockerLocation,
    slug_for_cell: str,
) -> None:
    """Кладёт по одному InventoryUnit товара в локер. Идемпотентно."""
    has_unit = (
        await session.scalars(
            select(InventoryUnit)
            .join(LockerCell, LockerCell.id == InventoryUnit.locker_cell_id)
            .where(
                InventoryUnit.product_id == product.id,
                LockerCell.locker_id == locker.id,
            )
        )
    ).first()
    if has_unit is not None:
        return

    # Создаём новую ячейку под этот товар.
    cells_count = (
        await session.scalars(
            select(LockerCell).where(LockerCell.locker_id == locker.id)
        )
    ).all()
    new_index = len(cells_count) + 1
    cell = LockerCell(
        id=uuid4(),
        locker_id=locker.id,
        external_cell_id=f"{locker.external_locker_id}-import-{slug_for_cell}",
        label=f"I{new_index}",
        size="M",
        status=LockerCellStatus.OCCUPIED,
        supports_return=True,
    )
    session.add(cell)
    await session.flush()

    unit = InventoryUnit(
        id=uuid4(),
        product_id=product.id,
        locker_cell_id=cell.id,
        serial_number=f"{(locker.external_locker_id or 'unknown').upper()}-{slug_for_cell.upper()}-IMPORT",
        barcode=f"{locker.external_locker_id}-{slug_for_cell}-import",
        status=InventoryStatus.AVAILABLE,
        condition_grade="A",
        condition_note="Готов к аренде",
    )
    session.add(unit)


async def _resolve_target_lockers(session: AsyncSession) -> list[LockerLocation]:
    lockers: list[LockerLocation] = []
    for provider, external in TARGET_LOCKERS:
        loc = (
            await session.scalars(
                select(LockerLocation).where(
                    LockerLocation.external_provider == provider,
                    LockerLocation.external_locker_id == external,
                )
            )
        ).first()
        if loc is None:
            logger.warning(
                "[skip locker] provider=%s external=%s not found", provider, external
            )
            continue
        lockers.append(loc)
    return lockers


async def _run(items_dir: Path, reset_images: bool = False) -> int:
    items = _scan_items_dir(items_dir)
    if not items:
        logger.error("no items to import in %s", items_dir)
        return 1

    logger.info("found %s items to import", len(items))

    async with SessionLocal() as session:
        category = await _ensure_category(session, DEFAULT_CATEGORY_SLUG)
        target_lockers = await _resolve_target_lockers(session)
        if not target_lockers:
            logger.error("no target lockers found, aborting")
            return 2

        for item in items:
            product, created = await _create_or_update_product(
                session, category_id=category.id, item=item
            )
            action = "created" if created else "found existing"
            logger.info("[product] %s (%s) — %s", item.name, item.slug, action)

            await _ensure_product_images(
                session, product=product, item=item, reset=reset_images
            )
            await _ensure_price_plans(session, product=product, item=item)

            for locker in target_lockers:
                await _place_in_locker(
                    session,
                    product=product,
                    locker=locker,
                    slug_for_cell=item.slug,
                )
            logger.info(
                "[product] %s placed in %s lockers", item.slug, len(target_lockers)
            )

        await session.commit()

    await engine.dispose()
    logger.info("import finished, %s items processed", len(items))
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--items-dir",
        default=os.path.join(ROOT, "items"),
        help="Папка с товарами (по умолчанию ./items от корня репо)",
    )
    parser.add_argument(
        "--reset-images",
        action="store_true",
        help=(
            "Удалить текущую обложку и галерею у каждого товара и перезалить "
            "из items/<slug>/. По умолчанию — нет, скрипт идемпотентный."
        ),
    )
    args = parser.parse_args()
    return asyncio.run(
        _run(Path(args.items_dir).resolve(), reset_images=args.reset_images)
    )


if __name__ == "__main__":
    raise SystemExit(main())
