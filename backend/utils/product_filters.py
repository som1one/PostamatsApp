from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_filter import ProductFilter
from backend.utils.lockers_utils import price_plan_to_minor_units


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_url_list(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    return normalized


def _normalize_filter_price_plan(item: dict[str, Any], index: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    try:
        duration_value = int(item.get("durationValue"))
        base_amount = int(item.get("baseAmount"))
    except (TypeError, ValueError):
        return None

    if duration_value < 1 or base_amount < 0:
        return None

    name = str(item.get("name") or "").strip()
    duration_type = str(item.get("durationType") or "").strip()
    if not name or not duration_type:
        return None

    return {
        "id": f"filter-plan-{index}",
        "name": name,
        "durationType": duration_type,
        "durationValue": duration_value,
        "baseAmount": base_amount,
        "currency": str(item.get("currency") or "RUB").strip() or "RUB",
        "isActive": bool(item.get("isActive", True)),
        "sortOrder": int(item.get("sortOrder") or 0),
    }


def serialize_product_filter(filter_item: ProductFilter | None) -> dict | None:
    if filter_item is None:
        return None
    return {
        "id": str(filter_item.id),
        "productId": str(filter_item.product_id),
        "name": filter_item.name,
        "shortDescription": filter_item.short_description,
        "fullDescription": filter_item.full_description,
        "rulesText": filter_item.rules_text,
        "kitDescription": filter_item.kit_description,
        "coverUrl": filter_item.cover_url,
        "galleryUrls": _normalize_url_list(filter_item.gallery_urls_json) or [],
        "tariffs": normalize_filter_price_plans(filter_item),
        "isActive": filter_item.is_active,
        "createdAt": filter_item.created_at.isoformat(),
        "updatedAt": filter_item.updated_at.isoformat(),
    }


async def load_product_filters_by_product_ids(
    db: AsyncSession,
    product_ids: list[UUID],
) -> dict[UUID, ProductFilter]:
    if not product_ids:
        return {}
    rows = (
        await db.scalars(
            select(ProductFilter).where(ProductFilter.product_id.in_(product_ids))
        )
    ).all()
    return {row.product_id: row for row in rows}


async def load_product_filter(
    db: AsyncSession,
    product_id: UUID,
) -> ProductFilter | None:
    return (
        await db.scalars(
            select(ProductFilter).where(ProductFilter.product_id == product_id).limit(1)
        )
    ).first()


def is_product_visible(
    product: Product,
    product_filter: ProductFilter | None,
) -> bool:
    if not product.is_active:
        return False
    if product_filter is None:
        return True
    return product_filter.is_active


def normalize_filter_price_plans(
    product_filter: ProductFilter | None,
) -> list[dict[str, Any]]:
    if product_filter is None or not product_filter.price_plans_json:
        return []

    plans: list[dict[str, Any]] = []
    for index, item in enumerate(product_filter.price_plans_json):
        normalized = _normalize_filter_price_plan(item, index)
        if normalized is None or not normalized["isActive"]:
            continue
        plans.append(normalized)

    plans.sort(
        key=lambda item: (
            int(item.get("sortOrder", 0)),
            int(item.get("baseAmount", 0)),
            str(item.get("durationType", "")),
            int(item.get("durationValue", 0)),
        )
    )
    return plans


def resolve_effective_price_plans(
    base_plans: list[dict[str, Any]],
    product_filter: ProductFilter | None,
) -> list[dict[str, Any]]:
    filter_plans = normalize_filter_price_plans(product_filter)
    return filter_plans or base_plans


def resolve_effective_cover_url(
    base_cover_url: str | None,
    product_filter: ProductFilter | None,
) -> str | None:
    if product_filter and _normalize_text(product_filter.cover_url):
        return _normalize_text(product_filter.cover_url)
    return base_cover_url


def resolve_effective_images(
    base_cover_url: str | None,
    base_images: list[dict[str, Any]],
    product_filter: ProductFilter | None,
) -> tuple[str | None, list[dict[str, Any]]]:
    cover_url = resolve_effective_cover_url(base_cover_url, product_filter)
    gallery_urls = _normalize_url_list(product_filter.gallery_urls_json if product_filter else None)
    if gallery_urls:
        return cover_url, [
            {
                "id": f"filter-image-{index}",
                "fileId": None,
                "url": url,
                "sortOrder": index,
            }
            for index, url in enumerate(gallery_urls)
        ]
    return cover_url, base_images


def resolve_effective_list_item(
    payload: dict[str, Any],
    product_filter: ProductFilter | None,
) -> dict[str, Any]:
    item = dict(payload)
    if product_filter is None:
        return item

    name = _normalize_text(product_filter.name)
    short_description = _normalize_text(product_filter.short_description)
    if name:
        item["name"] = name
    if short_description is not None:
        item["shortDescription"] = short_description

    item["coverUrl"] = resolve_effective_cover_url(item.get("coverUrl"), product_filter)

    plans = normalize_filter_price_plans(product_filter)
    if plans:
        min_plan = min(plans, key=lambda row: int(row["baseAmount"]))
        item["priceFrom"] = int(min_plan["baseAmount"])
        item["currency"] = str(min_plan["currency"])

    return item


def resolve_effective_detail_item(
    payload: dict[str, Any],
    product_filter: ProductFilter | None,
) -> dict[str, Any]:
    item = dict(payload)
    if product_filter is None:
        return item

    name = _normalize_text(product_filter.name)
    short_description = _normalize_text(product_filter.short_description)
    full_description = _normalize_text(product_filter.full_description)
    rules_text = _normalize_text(product_filter.rules_text)
    kit_description = _normalize_text(product_filter.kit_description)

    if name:
        item["name"] = name
    if short_description is not None:
        item["shortDescription"] = short_description
    if full_description is not None:
        item["fullDescription"] = full_description
    if rules_text is not None:
        item["rulesText"] = rules_text
    if kit_description is not None:
        item["kitDescription"] = kit_description

    item["coverUrl"], item["images"] = resolve_effective_images(
        item.get("coverUrl"),
        item.get("images", []),
        product_filter,
    )
    item["pricePlans"] = resolve_effective_price_plans(item.get("pricePlans", []), product_filter)
    return item


def find_effective_filter_price_plan(
    product_filter: ProductFilter | None,
    duration_type: str,
    duration_value: int,
) -> dict[str, Any] | None:
    for plan in normalize_filter_price_plans(product_filter):
        if (
            str(plan["durationType"]).strip().lower() == duration_type.strip().lower()
            and int(plan["durationValue"]) == duration_value
        ):
            return plan
    return None


def minor_to_major_decimal(amount_minor: int) -> Decimal:
    return (Decimal(amount_minor) / Decimal("100")).quantize(Decimal("0.01"))


def serialize_base_price_plan(plan: PricePlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "name": plan.name,
        "durationType": plan.duration_type,
        "durationValue": plan.duration_value,
        "baseAmount": price_plan_to_minor_units(plan.base_amount, plan.currency),
        "currency": plan.currency,
    }
