import json
import mimetypes
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote_plus, urlparse, urlunparse
from uuid import uuid4

import requests
from PIL import Image, ImageChops


ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "backend" / "dev.sqlite3"
ASSETS_DIR = ROOT_DIR / "assets" / "uploads" / "items"
CATALOG_URL = "https://beri-bery.ru/catalog/"
MOSCOW_CITY_SLUG = "moscow"
MOSCOW_TEST_LOCKER_ID = "60d6b35dd1644419803cce9e93508ff0"
NORMALIZED_IMAGE_SIZE = (1200, 1000)
NORMALIZED_IMAGE_PADDING = 90
DEFAULT_RULES_TEXT = (
    "Проверьте комплект и внешний вид при получении. "
    "Используйте товар по назначению и верните его в той же комплектации."
)


@dataclass(frozen=True)
class ProductOverride:
    category_slug: str
    brand: str | None
    kit_description: str | None
    rules_text: str | None = None


PRODUCT_OVERRIDES: dict[str, ProductOverride] = {
    "playstation-5": ProductOverride(
        category_slug="consoles",
        brand="Sony",
        kit_description="Приставка; HDMI кабель; кабель питания",
    ),
    "polaroid": ProductOverride(
        category_slug="photo",
        brand="Fujifilm",
        kit_description="Фотоаппарат моментальной печати; картриджи Instax Wide в комплект не входят",
    ),
    "avtonomnyj-projektor": ProductOverride(
        category_slug="projectors",
        brand=None,
        kit_description="Проектор; питание USB-C",
    ),
    "drel": ProductOverride(
        category_slug="tools",
        brand="Bosch",
        kit_description="Дрель; набор из 18 бит; магнитный адаптер",
    ),
    "moyushchij-pylesos": ProductOverride(
        category_slug="cleaning",
        brand=None,
        kit_description="Моющий пылесос; насадка для мягкой мебели; щелевая насадка",
    ),
    "otparivatel": ProductOverride(
        category_slug="home",
        brand="Spawnson",
        kit_description="Ручной отпариватель",
    ),
    "paroochistitel-karcher": ProductOverride(
        category_slug="cleaning",
        brand="Karcher",
        kit_description="Пароочиститель; насадки; салфетки",
    ),
    "perforator": ProductOverride(
        category_slug="tools",
        brand="Bosch",
        kit_description="Перфоратор; кейс; 3 бура; пика; лопатка; ограничитель глубины",
    ),
    "perforator-elitech": ProductOverride(
        category_slug="tools",
        brand="Elitech",
        kit_description="Перфоратор; 3 бура (6, 8, 10 мм); пика; лопатка; ограничитель глубины",
    ),
    "projektor": ProductOverride(
        category_slug="projectors",
        brand="Akenori",
        kit_description="Проектор; встроенные динамики; Wi-Fi; HDMI",
    ),
    "rashodniki-instax": ProductOverride(
        category_slug="photo",
        brand="Fujifilm",
        kit_description="Картридж Instax Wide на 10 снимков",
        rules_text=(
            "Подходит для Instax Wide 400. "
            "Возвращать картридж в постамат не нужно: аренда завершается автоматически."
        ),
    ),
    "robot-mojshchik-okon": ProductOverride(
        category_slug="cleaning",
        brand=None,
        kit_description="Робот; сменные салфетки из микрофибры; страховочный шнур",
    ),
    "shurupovert": ProductOverride(
        category_slug="tools",
        brand=None,
        kit_description="Шуруповерт; набор из 15 бит; 4 сверла (4, 6, 8, 10 мм)",
    ),
}

CATEGORY_TITLES = {
    "photo": "Фото",
}


def now_sql() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def extract_json_ld_blocks(html: str) -> list[dict[str, Any]]:
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    parsed: list[dict[str, Any]] = []
    for block in blocks:
        try:
            parsed.append(json.loads(block))
        except json.JSONDecodeError:
            continue
    return parsed


def load_catalog_items(session: requests.Session) -> list[dict[str, str]]:
    html = fetch_html(session, CATALOG_URL)
    for block in extract_json_ld_blocks(html):
        if block.get("@type") == "ItemList":
            return [
                {
                    "name": item["name"],
                    "url": item["url"],
                }
                for item in block.get("itemListElement", [])
            ]
    raise RuntimeError("Не удалось найти ItemList в каталоге beri-bery.ru")


def normalize_text(raw: str | None) -> str:
    text = (raw or "").replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n\n".join(lines).strip()


def short_description(full_description: str) -> str:
    compact = re.sub(r"\s+", " ", full_description).strip()
    if not compact:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", compact, maxsplit=1)
    first = parts[0].strip()
    if len(first) <= 180:
        return first
    return compact[:177].rstrip() + "..."


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1]


def load_product_payload(session: requests.Session, url: str) -> dict[str, Any]:
    html = fetch_html(session, url)
    for block in extract_json_ld_blocks(html):
        if block.get("@type") == "Product":
            return block
    raise RuntimeError(f"Не удалось найти Product json-ld для {url}")


def ensure_category(conn: sqlite3.Connection, slug: str) -> str:
    row = conn.execute("select id from product_categories where slug = ?", (slug,)).fetchone()
    if row:
        return row[0]

    if slug not in CATEGORY_TITLES:
        raise RuntimeError(f"Неизвестная категория: {slug}")

    max_sort = conn.execute("select coalesce(max(sort_order), 0) from product_categories").fetchone()[0]
    category_id = uuid4().hex
    timestamp = now_sql()
    conn.execute(
        """
        insert into product_categories (id, name, slug, sort_order, is_active, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (category_id, CATEGORY_TITLES[slug], slug, int(max_sort) + 10, 1, timestamp, timestamp),
    )
    return category_id


def ensure_media_file(
    conn: sqlite3.Connection,
    *,
    file_key: str,
    mime_type: str,
    file_size: int,
    original_name: str,
) -> str:
    row = conn.execute("select id from media_files where file_key = ?", (file_key,)).fetchone()
    if row:
        conn.execute(
            """
            update media_files
            set mime_type = ?, file_size = ?, original_name = ?, kind = ?
            where id = ?
            """,
            (mime_type, file_size, original_name, "PRODUCT_COVER", row[0]),
        )
        return row[0]

    media_id = uuid4().hex
    conn.execute(
        """
        insert into media_files (
            id, storage_provider, bucket, file_key, mime_type, file_size,
            original_name, kind, uploaded_by_user_id, uploaded_by_admin_id, created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, null, null, ?)
        """,
        (
            media_id,
            "local",
            "assets",
            file_key,
            mime_type,
            file_size,
            original_name,
            "PRODUCT_COVER",
            now_sql(),
        ),
    )
    return media_id


def _remove_flat_background(image: Image.Image, tolerance: int = 18) -> Image.Image:
    rgba = image.convert("RGBA")
    if rgba.getchannel("A").getextrema()[0] < 250:
        return rgba

    rgb = rgba.convert("RGB")
    background_color = rgb.getpixel((0, 0))
    background = Image.new("RGB", rgb.size, background_color)
    diff = ImageChops.difference(rgb, background).convert("L")
    alpha = diff.point(lambda value: 0 if value <= tolerance else 255)
    rgba.putalpha(alpha)
    return rgba


def _expand_bbox(bbox: tuple[int, int, int, int], image_size: tuple[int, int], margin: float = 0.035) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    pad_x = max(8, int(width * margin))
    pad_y = max(8, int(height * margin))
    image_width, image_height = image_size
    return (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(image_width, right + pad_x),
        min(image_height, bottom + pad_y),
    )


def normalize_product_image(content: bytes, suffix: str) -> bytes:
    image = Image.open(BytesIO(content))
    normalized = _remove_flat_background(image)
    bbox = normalized.getbbox()
    if bbox:
        normalized = normalized.crop(_expand_bbox(bbox, normalized.size))

    canvas = Image.new("RGBA", NORMALIZED_IMAGE_SIZE, (255, 255, 255, 0))
    max_width = NORMALIZED_IMAGE_SIZE[0] - (NORMALIZED_IMAGE_PADDING * 2)
    max_height = NORMALIZED_IMAGE_SIZE[1] - (NORMALIZED_IMAGE_PADDING * 2)
    normalized.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

    offset_x = (NORMALIZED_IMAGE_SIZE[0] - normalized.width) // 2
    offset_y = (NORMALIZED_IMAGE_SIZE[1] - normalized.height) // 2
    canvas.alpha_composite(normalized, (offset_x, offset_y))

    output = BytesIO()
    normalized_suffix = suffix.lower()
    if normalized_suffix in {".jpg", ".jpeg"}:
        canvas.convert("RGB").save(output, format="JPEG", quality=95, optimize=True)
    else:
        canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


def download_product_image(session: requests.Session, slug: str, url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    normalized_path = quote(unquote_plus(parsed.path))
    normalized_url = urlunparse(parsed._replace(path=normalized_path))

    response = session.get(normalized_url, timeout=30)
    response.raise_for_status()
    mime_type = response.headers.get("Content-Type", "image/png").split(";")[0].strip() or "image/png"
    suffix = Path(urlparse(url).path).suffix
    if not suffix:
        suffix = mimetypes.guess_extension(mime_type) or ".png"
    filename = f"beri-bery-{slug}{suffix.lower()}"
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    asset_path = ASSETS_DIR / filename
    asset_path.write_bytes(normalize_product_image(response.content, suffix))
    return f"uploads/items/{filename}", mime_type


def upsert_product(
    conn: sqlite3.Connection,
    *,
    category_id: str,
    slug: str,
    name: str,
    short_desc: str,
    full_desc: str,
    brand: str | None,
    cover_file_id: str,
    rules_text: str | None,
    kit_description: str | None,
) -> str:
    row = conn.execute("select id from products where slug = ?", (slug,)).fetchone()
    timestamp = now_sql()
    if row:
        product_id = row[0]
        conn.execute(
            """
            update products
            set category_id = ?, name = ?, short_description = ?, full_description = ?,
                rules_text = ?, kit_description = ?, brand = ?, cover_file_id = ?,
                is_active = ?, updated_at = ?
            where id = ?
            """,
            (
                category_id,
                name,
                short_desc,
                full_desc,
                rules_text,
                kit_description,
                brand,
                cover_file_id,
                1,
                timestamp,
                product_id,
            ),
        )
        return product_id

    product_id = uuid4().hex
    conn.execute(
        """
        insert into products (
            id, category_id, name, slug, short_description, full_description,
            specs_json, rules_text, kit_description, brand, cover_file_id,
            is_active, created_at, updated_at
        )
        values (?, ?, ?, ?, ?, ?, null, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            category_id,
            name,
            slug,
            short_desc,
            full_desc,
            rules_text,
            kit_description,
            brand,
            cover_file_id,
            1,
            timestamp,
            timestamp,
        ),
    )
    return product_id


def replace_product_images(conn: sqlite3.Connection, product_id: str, file_id: str) -> None:
    conn.execute("delete from product_images where product_id = ?", (product_id,))
    conn.execute(
        """
        insert into product_images (id, product_id, file_id, sort_order, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?)
        """,
        (uuid4().hex, product_id, file_id, 0, now_sql(), now_sql()),
    )


def replace_price_plan(conn: sqlite3.Connection, product_id: str, amount: int) -> None:
    conn.execute("delete from price_plans where product_id = ?", (product_id,))
    conn.execute(
        """
        insert into price_plans (
            id, product_id, name, duration_type, duration_value,
            base_amount, currency, is_active, sort_order, created_at, updated_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            product_id,
            "1 день",
            "day",
            1,
            str(amount),
            "RUB",
            1,
            0,
            now_sql(),
            now_sql(),
        ),
    )


def ensure_moscow_test_locker(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        select l.id
        from locker_locations l
        join cities c on c.id = l.city_id
        where c.slug = ? and l.id = ?
        limit 1
        """,
        (MOSCOW_CITY_SLUG, MOSCOW_TEST_LOCKER_ID),
    ).fetchone()
    if not row:
        raise RuntimeError("В базе не найден действующий постамат Москвы")
    return row[0]


def ensure_cell_for_unit(conn: sqlite3.Connection, locker_id: str, product_id: str, label_index: int) -> str:
    row = conn.execute(
        """
        select iu.id, lc.id
        from inventory_units iu
        join locker_cells lc on lc.id = iu.locker_cell_id
        where iu.product_id = ? and lc.locker_id = ?
        limit 1
        """,
        (product_id, locker_id),
    ).fetchone()
    if row:
        conn.execute(
            "update inventory_units set status = ?, updated_at = ? where id = ?",
            ("AVAILABLE", now_sql(), row[0]),
        )
        conn.execute(
            "update locker_cells set status = ?, updated_at = ? where id = ?",
            ("OCCUPIED", now_sql(), row[1]),
        )
        return row[1]

    cell_id = uuid4().hex
    label = f"M{label_index:02d}"
    external_cell_id = f"beri-bery-moscow-{label_index:02d}"
    conn.execute(
        """
        insert into locker_cells (
            id, locker_id, external_cell_id, label, size, status,
            supports_return, last_opened_at, last_closed_at, last_event_at,
            created_at, updated_at
        )
        values (?, ?, ?, ?, ?, ?, ?, null, null, null, ?, ?)
        """,
        (
            cell_id,
            locker_id,
            external_cell_id,
            label,
            "standard",
            "OCCUPIED",
            1,
            now_sql(),
            now_sql(),
        ),
    )
    conn.execute(
        """
        insert into inventory_units (
            id, product_id, locker_cell_id, serial_number, barcode, status,
            condition_grade, condition_note, purchase_price, purchase_date,
            last_check_at, created_at, updated_at
        )
        values (?, ?, ?, null, null, ?, null, null, null, null, null, ?, ?)
        """,
        (
            uuid4().hex,
            product_id,
            cell_id,
            "AVAILABLE",
            now_sql(),
            now_sql(),
        ),
    )
    return cell_id


def next_import_cell_index(conn: sqlite3.Connection, locker_id: str) -> int:
    rows = conn.execute(
        """
        select label
        from locker_cells
        where locker_id = ? and label like 'M__'
        order by label asc
        """,
        (locker_id,),
    ).fetchall()
    max_index = 0
    for (label,) in rows:
        try:
            max_index = max(max_index, int(str(label)[1:]))
        except ValueError:
            continue
    return max_index + 1


def import_catalog() -> None:
    session = requests.Session()
    catalog_items = load_catalog_items(session)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        locker_id = ensure_moscow_test_locker(conn)
        next_cell_index = next_import_cell_index(conn, locker_id)
        imported_count = 0

        for catalog_item in catalog_items:
            url = catalog_item["url"]
            slug = slug_from_url(url)
            override = PRODUCT_OVERRIDES.get(slug)
            if not override:
                raise RuntimeError(f"Для слага {slug} не настроен импорт")

            payload = load_product_payload(session, url)
            name = re.sub(r"\.\s*Аренда$", "", str(payload.get("name") or "")).strip()
            description = normalize_text(str(payload.get("description") or ""))
            short_desc = short_description(description)
            image_url = str(payload.get("image") or "").strip()
            offers = payload.get("offers") or []
            if not offers:
                raise RuntimeError(f"У товара {slug} нет offers в json-ld")
            base_price = int(float(offers[0]["price"]))

            category_id = ensure_category(conn, override.category_slug)
            file_key, mime_type = download_product_image(session, slug, image_url)
            file_path = ROOT_DIR / "assets" / Path(file_key)
            media_id = ensure_media_file(
                conn,
                file_key=file_key,
                mime_type=mime_type,
                file_size=file_path.stat().st_size,
                original_name=file_path.name,
            )

            product_id = upsert_product(
                conn,
                category_id=category_id,
                slug=slug,
                name=name,
                short_desc=short_desc,
                full_desc=description,
                brand=override.brand,
                cover_file_id=media_id,
                rules_text=override.rules_text or DEFAULT_RULES_TEXT,
                kit_description=override.kit_description,
            )
            replace_product_images(conn, product_id, media_id)
            replace_price_plan(conn, product_id, base_price)
            ensure_cell_for_unit(conn, locker_id, product_id, next_cell_index)
            next_cell_index += 1
            imported_count += 1

        conn.commit()
        print(f"Импортировано товаров: {imported_count}")
    finally:
        conn.close()


if __name__ == "__main__":
    import_catalog()
