"""Что поправили в админке — то синхронизация каталога больше не трогает.

Каталог сайта живёт в ``deploy/catalog-sync.bundle.json``, и каждая
выкладка накатывает его заново (``scripts/apply_catalog_bundle.py``).
Раньше она молча затирала правки из админки: тексты, фото, активность
товаров, настройки городов, а городские фильтры товаров удаляла вовсе.

Теперь у товара, города и фильтра товара есть ``admin_edited_fields`` —
список полей (в именах админского API: ``fullDescription``, ``isActive``…),
которые в админке действительно изменили. Админка дописывает туда только
поля, чьё значение поменялось: форма товара отправляет все поля разом.
Синхронизация пропускает эти поля и пишет в лог выкладки, что сохранила.

Чтобы каталог снова управлял полем, его надо убрать из списка (SQL).
"""

import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

BUNDLE_PATH = Path(__file__).resolve().parents[2] / "deploy" / "catalog-sync.bundle.json"


def _comparable(value: Any) -> Any:
    # Админка обрезает пробелы и пустой текст сохраняет как NULL: простое
    # сохранение карточки без правок не должно отнимать поле у каталога.
    if isinstance(value, str):
        return value.strip() or None
    return value


def changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> set[str]:
    return {
        key for key in after if _comparable(before.get(key)) != _comparable(after[key])
    }


def mark_admin_edited(obj: Any, fields: Iterable[str]) -> None:
    changed = set(fields)
    if not changed:
        return
    # Новый список, а не правка на месте: иначе SQLAlchemy не заметит
    # изменения JSON-колонки.
    obj.admin_edited_fields = sorted(set(obj.admin_edited_fields or []) | changed)


def admin_edited(obj: Any) -> frozenset[str]:
    return frozenset(getattr(obj, "admin_edited_fields", None) or [])


@lru_cache(maxsize=1)
def _bundle_slugs() -> tuple[frozenset[str], frozenset[str]]:
    try:
        bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset(), frozenset()
    products = frozenset(bundle.get("managedProductSlugs") or [])
    cities = frozenset(city["slug"] for city in bundle.get("cities") or [] if city.get("slug"))
    return products, cities


def is_catalog_product(slug: str) -> bool:
    """Товар из каталога сайта: выкладка находит его по slug."""
    return slug in _bundle_slugs()[0]


def is_catalog_city(slug: str) -> bool:
    return slug in _bundle_slugs()[1]
