from __future__ import annotations

import argparse
import json
import mimetypes
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = ROOT_DIR / "backend" / "dev.sqlite3"
DEFAULT_OUTPUT = ROOT_DIR / "deploy" / "catalog-sync.bundle.json"
DEFAULT_EXCLUDED_PREFIXES = ("test-",)


def _json_loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _normalize_minor_amount(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    text = str(value).strip()
    if not text:
        return 0
    return int(float(text))


def _normalize_major_amount(value: Any) -> str:
    if value is None:
        return "0.00"
    text = str(value).strip()
    if not text:
        return "0.00"
    try:
        return f"{float(text):.2f}"
    except ValueError:
        return text


def _repo_asset_path(file_key: str) -> str:
    return str((Path("assets") / file_key).as_posix())


def _repo_asset_file(file_key: str) -> Path:
    repo_asset = ROOT_DIR / "assets" / file_key
    if not repo_asset.exists():
        raise RuntimeError(f"Не найден asset для media file {file_key}: {repo_asset}")
    return repo_asset


def _media_payload(
    *,
    file_key: str,
    kind: str,
    repo_asset: Path,
    mime_type: str | None = None,
    original_name: str | None = None,
) -> dict[str, Any]:
    return {
        "fileKey": file_key,
        "mimeType": mime_type or mimetypes.guess_type(repo_asset.name)[0] or "application/octet-stream",
        "fileSize": int(repo_asset.stat().st_size),
        "originalName": original_name or repo_asset.name,
        "kind": kind,
        "repoAssetPath": _repo_asset_path(file_key),
    }


def _normalize_filter_asset_url(url: str | None) -> str | None:
    if not url:
        return None
    marker = "/assets/"
    idx = url.find(marker)
    if idx == -1:
        return None
    file_key = url[idx + len(marker) :].lstrip("/")
    if not file_key:
        return None
    return file_key


def _fetch_rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(query, params).fetchall())


def build_bundle(
    *,
    source_db: Path,
    excluded_prefixes: tuple[str, ...],
) -> dict[str, Any]:
    conn = sqlite3.connect(source_db)
    conn.row_factory = sqlite3.Row

    try:
        product_rows = _fetch_rows(
            conn,
            """
            select
                p.id,
                p.category_id,
                p.name,
                p.slug,
                p.short_description,
                p.full_description,
                p.specs_json,
                p.rules_text,
                p.kit_description,
                p.brand,
                p.cover_file_id,
                p.is_active,
                count(iu.id) as inventory_count
            from products p
            join inventory_units iu on iu.product_id = p.id
            where p.is_active = 1
            group by p.id
            having count(iu.id) > 0
            order by p.slug
            """,
        )

        selected_products = [
            row
            for row in product_rows
            if not any(str(row["slug"]).startswith(prefix) for prefix in excluded_prefixes)
        ]
        selected_product_ids = [str(row["id"]) for row in selected_products]
        selected_product_slugs = [str(row["slug"]) for row in selected_products]

        if not selected_product_ids:
            raise RuntimeError("В source DB не найдено активных товаров для bundle.")

        category_ids = sorted({str(row["category_id"]) for row in selected_products})
        categories = [
            {
                "slug": str(row["slug"]),
                "name": str(row["name"]),
                "sortOrder": int(row["sort_order"]),
                "isActive": bool(row["is_active"]),
            }
            for row in _fetch_rows(
                conn,
                f"""
                select id, slug, name, sort_order, is_active
                from product_categories
                where id in ({",".join("?" for _ in category_ids)})
                order by sort_order asc, name asc
                """,
                tuple(category_ids),
            )
        ]
        categories_by_id = {
            str(row["id"]): str(row["slug"])
            for row in _fetch_rows(
                conn,
                f"""
                select id, slug
                from product_categories
                where id in ({",".join("?" for _ in category_ids)})
                """,
                tuple(category_ids),
            )
        }

        price_plan_rows = _fetch_rows(
            conn,
            f"""
            select product_id, name, duration_type, duration_value, base_amount, currency, is_active, sort_order
            from price_plans
            where product_id in ({",".join("?" for _ in selected_product_ids)})
            order by product_id asc, sort_order asc, base_amount asc
            """,
            tuple(selected_product_ids),
        )
        plans_by_product_id: dict[str, list[dict[str, Any]]] = {}
        for row in price_plan_rows:
            plans_by_product_id.setdefault(str(row["product_id"]), []).append(
                {
                    "name": str(row["name"]),
                    "durationType": str(row["duration_type"]),
                    "durationValue": int(row["duration_value"]),
                    "baseAmount": _normalize_major_amount(row["base_amount"]),
                    "currency": str(row["currency"]),
                    "isActive": bool(row["is_active"]),
                    "sortOrder": int(row["sort_order"]),
                }
            )

        image_rows = _fetch_rows(
            conn,
            f"""
            select product_id, file_id, sort_order
            from product_images
            where product_id in ({",".join("?" for _ in selected_product_ids)})
            order by product_id asc, sort_order asc, created_at asc
            """,
            tuple(selected_product_ids),
        )
        image_file_ids = [str(row["file_id"]) for row in image_rows]
        gallery_file_ids_by_product_id: dict[str, list[str]] = {}
        for row in image_rows:
            gallery_file_ids_by_product_id.setdefault(str(row["product_id"]), []).append(
                str(row["file_id"])
            )

        filter_rows = _fetch_rows(
            conn,
            f"""
            select
                product_id,
                name,
                short_description,
                full_description,
                rules_text,
                kit_description,
                cover_url,
                gallery_urls_json,
                price_plans_json,
                is_active
            from product_filters
            where product_id in ({",".join("?" for _ in selected_product_ids)})
            """,
            tuple(selected_product_ids),
        )
        filters_by_product_id: dict[str, dict[str, Any]] = {}
        filter_media_kinds: dict[str, str] = {}
        for row in filter_rows:
            gallery_urls = _json_loads(row["gallery_urls_json"]) or []
            cover_file_key = _normalize_filter_asset_url(row["cover_url"])
            gallery_file_keys = [
                item
                for item in (
                    _normalize_filter_asset_url(url) for url in gallery_urls if isinstance(url, str)
                )
                if item
            ]
            if cover_file_key:
                filter_media_kinds[cover_file_key] = "product_cover"
            for file_key in gallery_file_keys:
                filter_media_kinds.setdefault(file_key, "product_gallery")
            filter_payload = {
                "name": row["name"],
                "shortDescription": row["short_description"],
                "fullDescription": row["full_description"],
                "rulesText": row["rules_text"],
                "kitDescription": row["kit_description"],
                "coverFileKey": cover_file_key,
                "galleryFileKeys": gallery_file_keys,
                "pricePlans": _json_loads(row["price_plans_json"]) or [],
                "isActive": bool(row["is_active"]),
            }
            filters_by_product_id[str(row["product_id"])] = filter_payload

        cover_file_ids = [str(row["cover_file_id"]) for row in selected_products if row["cover_file_id"]]
        media_file_ids = sorted(set(cover_file_ids + image_file_ids))
        media_rows: list[sqlite3.Row] = []
        media_row_clauses: list[str] = []
        media_row_params: list[str] = []
        if media_file_ids:
            media_row_clauses.append(f"id in ({','.join('?' for _ in media_file_ids)})")
            media_row_params.extend(media_file_ids)
        if filter_media_kinds:
            filter_file_keys = sorted(filter_media_kinds)
            media_row_clauses.append(f"file_key in ({','.join('?' for _ in filter_file_keys)})")
            media_row_params.extend(filter_file_keys)
        if media_row_clauses:
            media_rows = _fetch_rows(
                conn,
                f"""
                select id, storage_provider, bucket, file_key, mime_type, file_size, original_name, kind
                from media_files
                where {' or '.join(media_row_clauses)}
                order by file_key asc
                """,
                tuple(media_row_params),
            )
        media_by_id = {str(row["id"]): row for row in media_rows}
        media_files: list[dict[str, Any]] = []
        seen_media_file_keys: set[str] = set()
        for row in media_rows:
            file_key = str(row["file_key"])
            repo_asset = _repo_asset_file(file_key)
            if not repo_asset.exists():
                raise RuntimeError(f"Не найден asset для media file {file_key}: {repo_asset}")
            media_files.append(
                {
                    "fileKey": file_key,
                    "mimeType": str(row["mime_type"]),
                    "fileSize": int(repo_asset.stat().st_size),
                    "originalName": str(row["original_name"]) if row["original_name"] else repo_asset.name,
                    "kind": str(row["kind"]),
                    "repoAssetPath": _repo_asset_path(file_key),
                }
            )
            seen_media_file_keys.add(file_key)
        for file_key, kind in sorted(filter_media_kinds.items()):
            if file_key in seen_media_file_keys:
                continue
            media_files.append(
                _media_payload(
                    file_key=file_key,
                    kind=kind,
                    repo_asset=_repo_asset_file(file_key),
                )
            )

        products: list[dict[str, Any]] = []
        for row in selected_products:
            product_id = str(row["id"])
            cover_file_key = None
            if row["cover_file_id"]:
                media_row = media_by_id.get(str(row["cover_file_id"]))
                cover_file_key = str(media_row["file_key"]) if media_row else None
            gallery_file_keys = []
            for file_id in gallery_file_ids_by_product_id.get(product_id, []):
                media_row = media_by_id.get(file_id)
                if media_row is not None:
                    gallery_file_keys.append(str(media_row["file_key"]))

            products.append(
                {
                    "slug": str(row["slug"]),
                    "name": str(row["name"]),
                    "brand": row["brand"],
                    "shortDescription": row["short_description"],
                    "fullDescription": row["full_description"],
                    "rulesText": row["rules_text"],
                    "kitDescription": row["kit_description"],
                    "specsJson": _json_loads(row["specs_json"]),
                    "categorySlug": categories_by_id[str(row["category_id"])],
                    "coverFileKey": cover_file_key,
                    "galleryFileKeys": gallery_file_keys,
                    "pricePlans": plans_by_product_id.get(product_id, []),
                    "filter": filters_by_product_id.get(product_id),
                    "isActive": bool(row["is_active"]),
                }
            )

        inventory_rows = _fetch_rows(
            conn,
            f"""
            select
                iu.product_id,
                iu.serial_number,
                iu.barcode,
                iu.status,
                iu.condition_grade,
                iu.condition_note,
                iu.purchase_price,
                iu.purchase_date,
                iu.last_check_at,
                lc.external_cell_id,
                lc.label as cell_label,
                lc.size,
                lc.status as cell_status,
                lc.supports_return,
                lc.last_opened_at,
                lc.last_closed_at,
                lc.last_event_at,
                l.name as locker_name,
                l.address,
                l.lat,
                l.lon,
                l.status as locker_status,
                l.working_hours_json,
                l.external_provider,
                l.external_locker_id,
                l.partner_name,
                l.last_online_at,
                c.slug as city_slug,
                c.name as city_name,
                c.timezone as city_timezone,
                c.is_active as city_is_active,
                c.sort_order as city_sort_order
            from inventory_units iu
            join locker_cells lc on lc.id = iu.locker_cell_id
            join locker_locations l on l.id = lc.locker_id
            join cities c on c.id = l.city_id
            where iu.product_id in ({",".join("?" for _ in selected_product_ids)})
            order by c.sort_order asc, l.name asc, lc.label asc, iu.serial_number asc, iu.barcode asc
            """,
            tuple(selected_product_ids),
        )

        cities_by_slug: dict[str, dict[str, Any]] = {}
        lockers_by_key: dict[tuple[str | None, str | None], dict[str, Any]] = {}
        cells_by_key: dict[tuple[str | None, str | None, str | None, str | None], dict[str, Any]] = {}
        inventory_units: list[dict[str, Any]] = []
        product_slug_by_id = {str(row["id"]): str(row["slug"]) for row in selected_products}

        for row in inventory_rows:
            city_slug = str(row["city_slug"])
            cities_by_slug.setdefault(
                city_slug,
                {
                    "slug": city_slug,
                    "name": str(row["city_name"]),
                    "timezone": str(row["city_timezone"]),
                    "isActive": bool(row["city_is_active"]),
                    "sortOrder": int(row["city_sort_order"]),
                },
            )

            locker_key = (
                str(row["external_provider"]) if row["external_provider"] is not None else None,
                str(row["external_locker_id"]) if row["external_locker_id"] is not None else None,
            )
            lockers_by_key.setdefault(
                locker_key,
                {
                    "citySlug": city_slug,
                    "name": str(row["locker_name"]),
                    "address": str(row["address"]),
                    "lat": float(row["lat"]) if row["lat"] is not None else None,
                    "lon": float(row["lon"]) if row["lon"] is not None else None,
                    "status": str(row["locker_status"]),
                    "workingHoursJson": _json_loads(row["working_hours_json"]),
                    "externalProvider": locker_key[0],
                    "externalLockerId": locker_key[1],
                    "partnerName": row["partner_name"],
                    "lastOnlineAt": row["last_online_at"],
                },
            )

            cell_key = (
                locker_key[0],
                locker_key[1],
                str(row["external_cell_id"]) if row["external_cell_id"] is not None else None,
                str(row["cell_label"]) if row["cell_label"] is not None else None,
            )
            cells_by_key.setdefault(
                cell_key,
                {
                    "lockerExternalProvider": locker_key[0],
                    "lockerExternalLockerId": locker_key[1],
                    "externalCellId": cell_key[2],
                    "label": cell_key[3],
                    "size": row["size"],
                    "status": str(row["cell_status"]),
                    "supportsReturn": bool(row["supports_return"]),
                    "lastOpenedAt": row["last_opened_at"],
                    "lastClosedAt": row["last_closed_at"],
                    "lastEventAt": row["last_event_at"],
                },
            )

            inventory_units.append(
                {
                    "productSlug": product_slug_by_id[str(row["product_id"])],
                    "lockerExternalProvider": locker_key[0],
                    "lockerExternalLockerId": locker_key[1],
                    "cellExternalCellId": cell_key[2],
                    "cellLabel": cell_key[3],
                    "serialNumber": row["serial_number"],
                    "barcode": row["barcode"],
                    "status": str(row["status"]),
                    "conditionGrade": row["condition_grade"],
                    "conditionNote": row["condition_note"],
                    "purchasePrice": _normalize_major_amount(row["purchase_price"])
                    if row["purchase_price"] is not None
                    else None,
                    "purchaseDate": row["purchase_date"],
                    "lastCheckAt": row["last_check_at"],
                }
            )

        return {
            "meta": {
                "generatedAt": datetime.now(UTC).isoformat(),
                "sourceDb": str(source_db.relative_to(ROOT_DIR)),
                "excludedSlugPrefixes": list(excluded_prefixes),
                "productCount": len(products),
                "lockerCount": len(lockers_by_key),
                "inventoryUnitCount": len(inventory_units),
            },
            "categories": categories,
            "mediaFiles": media_files,
            "products": products,
            "cities": list(cities_by_slug.values()),
            "lockers": list(lockers_by_key.values()),
            "cells": list(cells_by_key.values()),
            "inventoryUnits": inventory_units,
            "managedProductSlugs": selected_product_slugs,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Экспортирует локальный каталог и связанные данные в bundle для переноса на сервер.",
    )
    parser.add_argument(
        "--source-db",
        type=Path,
        default=DEFAULT_SOURCE_DB,
        help=f"Путь к source SQLite DB (по умолчанию: {DEFAULT_SOURCE_DB})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Куда сохранить bundle JSON (по умолчанию: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--exclude-slug-prefix",
        action="append",
        default=[],
        help="Исключить продукты по префиксу slug. Можно передать несколько раз.",
    )
    args = parser.parse_args()

    excluded_prefixes = tuple(args.exclude_slug_prefix or DEFAULT_EXCLUDED_PREFIXES)
    bundle = build_bundle(source_db=args.source_db.resolve(), excluded_prefixes=excluded_prefixes)

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Bundle saved to {output_path} "
        f"(products={bundle['meta']['productCount']}, "
        f"lockers={bundle['meta']['lockerCount']}, "
        f"units={bundle['meta']['inventoryUnitCount']})"
    )


if __name__ == "__main__":
    main()
