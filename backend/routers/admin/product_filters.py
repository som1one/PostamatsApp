from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.inventory_unit import InventoryUnit
from backend.models.product import Product
from backend.models.product_filter import ProductFilter
from backend.routers.admin.auth import get_current_admin
from backend.schemas.product_filter_schemas import (
    AdminCreateProductFilterPayload,
    AdminUpdateProductFilterPayload,
)
from backend.utils.admin_audit import record_admin_audit
from backend.utils.product_filters import serialize_product_filter

router = APIRouter(prefix="/api/admin/product-filters", tags=["admin-product-filters"])


async def _require_admin_or_403(
    request: Request,
    db: AsyncSession,
):
    try:
        return await get_current_admin(request, db)
    except HTTPException as exc:
        raise HTTPException(status_code=403, detail="FORBIDDEN") from exc


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_gallery_urls(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def _normalize_tariffs(values: list) -> list[dict]:
    return [item.model_dump() for item in values]


def _serialize_item(product: Product, product_filter: ProductFilter | None) -> dict:
    return {
        "product": {
            "id": str(product.id),
            "name": product.name,
            "slug": product.slug,
            "brand": product.brand,
            "isActive": product.is_active,
        },
        "filter": serialize_product_filter(product_filter),
    }


async def _get_filterable_product_ids(db: AsyncSession) -> list[UUID]:
    rows = await db.execute(
        select(distinct(InventoryUnit.product_id)).order_by(InventoryUnit.product_id)
    )
    return [row[0] for row in rows if row[0] is not None]


@router.get("")
async def list_product_filters(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_or_403(request, db)
    product_ids = await _get_filterable_product_ids(db)
    if not product_ids:
        return {"data": {"items": []}, "meta": {"total": 0}}

    products = (
        await db.scalars(
            select(Product).where(Product.id.in_(product_ids)).order_by(Product.name.asc())
        )
    ).all()
    filters = (
        await db.scalars(
            select(ProductFilter).where(ProductFilter.product_id.in_(product_ids))
        )
    ).all()
    filters_by_product_id = {item.product_id: item for item in filters}

    return {
        "data": {
            "items": [
                _serialize_item(product, filters_by_product_id.get(product.id))
                for product in products
            ]
        },
        "meta": {"total": len(products)},
    }


@router.get("/{product_id}")
async def get_product_filter(
    product_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_or_403(request, db)
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    product_filter = (
        await db.scalars(
            select(ProductFilter).where(ProductFilter.product_id == product_id).limit(1)
        )
    ).first()
    return {"data": _serialize_item(product, product_filter)}


@router.post("")
async def create_product_filter(
    request: Request,
    payload: AdminCreateProductFilterPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await _require_admin_or_403(request, db)

    product = await db.get(Product, payload.productId)
    if product is None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")

    existing = (
        await db.scalars(
            select(ProductFilter).where(ProductFilter.product_id == payload.productId).limit(1)
        )
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="PRODUCT_FILTER_ALREADY_EXISTS")

    product_filter = ProductFilter(
        product_id=payload.productId,
        name=_normalize_optional_text(payload.name),
        short_description=_normalize_optional_text(payload.shortDescription),
        full_description=_normalize_optional_text(payload.fullDescription),
        rules_text=_normalize_optional_text(payload.rulesText),
        kit_description=_normalize_optional_text(payload.kitDescription),
        cover_url=_normalize_optional_text(payload.coverUrl),
        gallery_urls_json=_normalize_gallery_urls(payload.galleryUrls),
        price_plans_json=_normalize_tariffs(payload.tariffs),
        is_active=payload.isActive,
    )
    db.add(product_filter)

    try:
        await db.flush()
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="product_filter.create",
            request=request,
            resource_type="product_filter",
            resource_id=product_filter.id,
            payload={"productId": str(payload.productId)},
        )
        await db.commit()
        await db.refresh(product_filter)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="PRODUCT_FILTER_CREATE_FAILED") from exc

    return {"data": _serialize_item(product, product_filter)}


@router.patch("/{product_id}")
async def update_product_filter(
    product_id: UUID,
    request: Request,
    payload: AdminUpdateProductFilterPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await _require_admin_or_403(request, db)

    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")

    product_filter = (
        await db.scalars(
            select(ProductFilter).where(ProductFilter.product_id == product_id).limit(1)
        )
    ).first()
    if product_filter is None:
        raise HTTPException(status_code=404, detail="PRODUCT_FILTER_NOT_FOUND")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        product_filter.name = _normalize_optional_text(data["name"])
    if "shortDescription" in data:
        product_filter.short_description = _normalize_optional_text(data["shortDescription"])
    if "fullDescription" in data:
        product_filter.full_description = _normalize_optional_text(data["fullDescription"])
    if "rulesText" in data:
        product_filter.rules_text = _normalize_optional_text(data["rulesText"])
    if "kitDescription" in data:
        product_filter.kit_description = _normalize_optional_text(data["kitDescription"])
    if "coverUrl" in data:
        product_filter.cover_url = _normalize_optional_text(data["coverUrl"])
    if "galleryUrls" in data:
        product_filter.gallery_urls_json = _normalize_gallery_urls(data["galleryUrls"])
    if "tariffs" in data:
        product_filter.price_plans_json = _normalize_tariffs(payload.tariffs or [])
    if "isActive" in data:
        product_filter.is_active = bool(data["isActive"])

    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="product_filter.update",
            request=request,
            resource_type="product_filter",
            resource_id=product_filter.id,
            payload={"productId": str(product_id), "fields": list(data.keys())},
        )
        await db.commit()
        await db.refresh(product_filter)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="PRODUCT_FILTER_UPDATE_FAILED") from exc

    return {"data": _serialize_item(product, product_filter)}


@router.delete("/{product_id}")
async def delete_product_filter(
    product_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await _require_admin_or_403(request, db)

    product_filter = (
        await db.scalars(
            select(ProductFilter).where(ProductFilter.product_id == product_id).limit(1)
        )
    ).first()
    if product_filter is None:
        raise HTTPException(status_code=404, detail="PRODUCT_FILTER_NOT_FOUND")

    try:
        filter_id = product_filter.id
        await db.delete(product_filter)
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="product_filter.delete",
            request=request,
            resource_type="product_filter",
            resource_id=filter_id,
            payload={"productId": str(product_id)},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="PRODUCT_FILTER_DELETE_FAILED") from exc

    return {"data": {"deleted": True, "productId": str(product_id)}}
