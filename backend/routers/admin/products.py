import re
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.inventory_unit import InventoryUnit
from backend.models.media_file import MediaFile
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.product_image import ProductImage
from backend.routers.admin.auth import get_current_admin
from backend.schemas.admin_panel_schemas import AdminCreateProductPayload, AdminUpdateProductPayload
from backend.utils.admin_audit import record_admin_audit
from backend.utils.products_utils import load_media_files_by_ids, load_product_images_with_urls, public_media_url

router = APIRouter(prefix="/api/admin/products", tags=["admin-products"])

SLUG_PATTERN = re.compile(r"[^a-z0-9-]+")


def normalize_product_slug(raw_slug: str) -> str:
    normalized = SLUG_PATTERN.sub("-", raw_slug.strip().lower()).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized


def _resolve_new_product_slug(name: str, explicit: str | None) -> str:
    if explicit and explicit.strip():
        s = normalize_product_slug(explicit)
        if s:
            return s
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    s = normalize_product_slug(ascii_part)
    if s:
        return s
    return f"item-{uuid4().hex[:12]}"


def _dedupe_uuid_list(values: list[UUID]) -> list[UUID]:
    out: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


async def _validate_image_media_file_ids(
    db: AsyncSession, file_ids: list[UUID]
) -> dict[UUID, MediaFile]:
    normalized_ids = _dedupe_uuid_list(file_ids)
    if not normalized_ids:
        return {}
    media_map = await load_media_files_by_ids(db, normalized_ids)
    missing_ids = [str(fid) for fid in normalized_ids if fid not in media_map]
    if missing_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Не найдены media file ids: {', '.join(missing_ids)}",
        )
    not_images = [
        str(fid)
        for fid in normalized_ids
        if not str((media_map[fid].mime_type or "")).lower().startswith("image/")
    ]
    if not_images:
        raise HTTPException(
            status_code=422,
            detail=f"Файлы должны быть image/*: {', '.join(not_images)}",
        )
    return media_map


async def _sync_product_gallery(db: AsyncSession, product_id: UUID, gallery_file_ids: list[UUID]) -> None:
    current = (
        await db.scalars(
            select(ProductImage).where(ProductImage.product_id == product_id)
        )
    ).all()
    current_by_file_id = {row.file_id: row for row in current}
    target_set = set(gallery_file_ids)

    for row in current:
        if row.file_id not in target_set:
            await db.delete(row)

    for sort_order, file_id in enumerate(gallery_file_ids):
        row = current_by_file_id.get(file_id)
        if row:
            row.sort_order = sort_order
            continue
        db.add(
            ProductImage(
                product_id=product_id,
                file_id=file_id,
                sort_order=sort_order,
            )
        )


def _serialize_plan(p: PricePlan) -> dict:
    amt = p.base_amount
    if isinstance(amt, Decimal):
        amt = float(amt)
    return {
        "id": str(p.id),
        "name": p.name,
        "durationType": p.duration_type,
        "durationValue": p.duration_value,
        "baseAmount": amt,
        "currency": p.currency,
        "isActive": p.is_active,
        "sortOrder": p.sort_order,
    }


def _serialize_product_row(
    p: Product,
    category_name: str | None,
    unit_count: int,
    cover_url: str | None,
) -> dict:
    return {
        "id": str(p.id),
        "categoryId": str(p.category_id),
        "categoryName": category_name,
        "name": p.name,
        "slug": p.slug,
        "shortDescription": p.short_description,
        "isActive": p.is_active,
        "brand": p.brand,
        "unitCount": unit_count,
        "coverUrl": cover_url,
        "createdAt": p.created_at.isoformat(),
        "updatedAt": p.updated_at.isoformat(),
    }


@router.get("")
async def list_admin_products(
    request: Request,
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, max_length=200),
    category_id: UUID | None = Query(None, alias="categoryId"),
    is_active: bool | None = Query(None, alias="isActive"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    await get_current_admin(request, db)

    filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters.append(or_(Product.name.ilike(term), Product.slug.ilike(term)))
    if category_id is not None:
        filters.append(Product.category_id == category_id)
    if is_active is not None:
        filters.append(Product.is_active.is_(is_active))

    count_stmt = select(func.count()).select_from(Product)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await db.scalar(count_stmt)) or 0

    stmt = select(Product)
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.order_by(Product.name.asc()).offset((page - 1) * limit).limit(limit)
    products = (await db.scalars(stmt)).all()

    cat_ids = list({p.category_id for p in products})
    cats = (
        (await db.scalars(select(ProductCategory).where(ProductCategory.id.in_(cat_ids)))).all()
        if cat_ids
        else []
    )
    cat_by_id = {c.id: c.name for c in cats}

    pids = [p.id for p in products]
    unit_counts: dict[UUID, int] = {}
    if pids:
        uc_stmt = (
            select(InventoryUnit.product_id, func.count(InventoryUnit.id))
            .where(InventoryUnit.product_id.in_(pids))
            .group_by(InventoryUnit.product_id)
        )
        for row in (await db.execute(uc_stmt)).all():
            unit_counts[row[0]] = int(row[1])

    cover_ids = [p.cover_file_id for p in products if p.cover_file_id]
    media_map = await load_media_files_by_ids(db, [cid for cid in cover_ids if cid])

    items = []
    for p in products:
        cover_url = None
        if p.cover_file_id and p.cover_file_id in media_map:
            cover_url = public_media_url(media_map[p.cover_file_id].file_key)
        items.append(
            _serialize_product_row(
                p,
                cat_by_id.get(p.category_id),
                unit_counts.get(p.id, 0),
                cover_url,
            )
        )

    return {
        "data": {"products": items},
        "meta": {"page": page, "limit": limit, "total": int(total)},
    }


@router.get("/{product_id}")
async def get_admin_product(
    request: Request,
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден")

    category = await db.get(ProductCategory, product.category_id)
    plans = (
        await db.scalars(
            select(PricePlan)
            .where(PricePlan.product_id == product.id)
            .order_by(PricePlan.sort_order.asc(), PricePlan.name.asc())
        )
    ).all()
    images = await load_product_images_with_urls(db, product.id)

    cover_url = None
    if product.cover_file_id:
        media_map = await load_media_files_by_ids(db, [product.cover_file_id])
        m = media_map.get(product.cover_file_id)
        if m:
            cover_url = public_media_url(m.file_key)

    return {
        "data": {
            "product": {
                "id": str(product.id),
                "categoryId": str(product.category_id),
                "categoryName": category.name if category else None,
                "name": product.name,
                "slug": product.slug,
                "shortDescription": product.short_description,
                "fullDescription": product.full_description,
                "rulesText": product.rules_text,
                "kitDescription": product.kit_description,
                "brand": product.brand,
                "specsJson": product.specs_json,
                "isActive": product.is_active,
                "coverFileId": str(product.cover_file_id) if product.cover_file_id else None,
                "coverUrl": cover_url,
                "images": images,
                "createdAt": product.created_at.isoformat(),
                "updatedAt": product.updated_at.isoformat(),
                "pricePlans": [_serialize_plan(pl) for pl in plans],
            }
        }
    }


@router.post("")
async def create_admin_product(
    request: Request,
    payload: AdminCreateProductPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    cat = await db.get(ProductCategory, payload.categoryId)
    if cat is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название обязательно")

    slug = _resolve_new_product_slug(name, payload.slug)
    conflict = await db.scalar(select(Product.id).where(Product.slug == slug))
    if conflict is not None:
        raise HTTPException(status_code=409, detail="Товар с таким slug уже существует")

    gallery_file_ids = _dedupe_uuid_list(payload.galleryFileIds or [])
    media_ids_to_validate = gallery_file_ids.copy()
    if payload.coverFileId is not None:
        media_ids_to_validate.insert(0, payload.coverFileId)
    media_map = await _validate_image_media_file_ids(db, media_ids_to_validate)

    product = Product(
        category_id=payload.categoryId,
        name=name,
        slug=slug,
        short_description=payload.shortDescription.strip() if payload.shortDescription else None,
        full_description=payload.fullDescription.strip() if payload.fullDescription else None,
        rules_text=payload.rulesText.strip() if payload.rulesText else None,
        kit_description=payload.kitDescription.strip() if payload.kitDescription else None,
        brand=payload.brand.strip() if payload.brand else None,
        specs_json=payload.specsJson,
        is_active=payload.isActive,
        cover_file_id=payload.coverFileId,
    )
    db.add(product)

    try:
        await db.flush()
        await _sync_product_gallery(db, product.id, gallery_file_ids)
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="product.create",
            request=request,
            resource_type="product",
            resource_id=product.id,
            payload={
                "name": product.name,
                "slug": product.slug,
                "coverFileId": str(product.cover_file_id) if product.cover_file_id else None,
                "galleryCount": len(gallery_file_ids),
            },
        )
        await db.commit()
        await db.refresh(product)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось создать товар") from exc

    category = await db.get(ProductCategory, product.category_id)
    cover_url = None
    if product.cover_file_id and product.cover_file_id in media_map:
        cover_url = public_media_url(media_map[product.cover_file_id].file_key)
    return {
        "data": {
            "product": _serialize_product_row(product, category.name if category else None, 0, cover_url),
        }
    }


@router.patch("/{product_id}")
async def update_admin_product(
    request: Request,
    product_id: UUID,
    payload: AdminUpdateProductPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден")

    data = payload.model_dump(exclude_unset=True)
    gallery_file_ids: list[UUID] | None = None
    if "galleryFileIds" in data and data["galleryFileIds"] is not None:
        gallery_file_ids = _dedupe_uuid_list(data["galleryFileIds"])

    media_ids_to_validate: list[UUID] = []
    if "coverFileId" in data and data["coverFileId"] is not None:
        media_ids_to_validate.append(data["coverFileId"])
    if gallery_file_ids is not None:
        media_ids_to_validate.extend(gallery_file_ids)
    media_map = await _validate_image_media_file_ids(db, media_ids_to_validate)

    if "categoryId" in data and data["categoryId"] is not None:
        cat = await db.get(ProductCategory, data["categoryId"])
        if cat is None:
            raise HTTPException(status_code=404, detail="Категория не найдена")
        product.category_id = data["categoryId"]

    if "name" in data and data["name"] is not None:
        nm = data["name"].strip()
        if not nm:
            raise HTTPException(status_code=422, detail="Название не может быть пустым")
        product.name = nm

    if "slug" in data and data["slug"] is not None:
        slug = normalize_product_slug(data["slug"])
        if not slug:
            raise HTTPException(status_code=422, detail="Slug должен содержать латиницу или цифры")
        conflict = await db.scalar(select(Product.id).where(Product.slug == slug, Product.id != product_id))
        if conflict is not None:
            raise HTTPException(status_code=409, detail="Товар с таким slug уже существует")
        product.slug = slug

    if "shortDescription" in data:
        product.short_description = (
            data["shortDescription"].strip() if data["shortDescription"] else None
        )
    if "fullDescription" in data:
        product.full_description = data["fullDescription"].strip() if data["fullDescription"] else None
    if "rulesText" in data:
        product.rules_text = data["rulesText"].strip() if data["rulesText"] else None
    if "kitDescription" in data:
        product.kit_description = data["kitDescription"].strip() if data["kitDescription"] else None
    if "brand" in data:
        product.brand = data["brand"].strip() if data["brand"] else None
    if "isActive" in data and data["isActive"] is not None:
        product.is_active = data["isActive"]
    if "specsJson" in data:
        product.specs_json = data["specsJson"]
    if "coverFileId" in data:
        product.cover_file_id = data["coverFileId"]
    if gallery_file_ids is not None:
        await _sync_product_gallery(db, product.id, gallery_file_ids)

    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="product.update",
            request=request,
            resource_type="product",
            resource_id=product.id,
            payload={
                "fields": list(data.keys()),
                "coverFileId": str(product.cover_file_id) if product.cover_file_id else None,
                "galleryCount": len(gallery_file_ids) if gallery_file_ids is not None else None,
            },
        )
        await db.commit()
        await db.refresh(product)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось обновить товар") from exc

    category = await db.get(ProductCategory, product.category_id)
    uc = await db.scalar(
        select(func.count()).select_from(InventoryUnit).where(InventoryUnit.product_id == product.id)
    )
    cover_url = None
    if product.cover_file_id:
        m = media_map.get(product.cover_file_id)
        if not m:
            m = (await load_media_files_by_ids(db, [product.cover_file_id])).get(product.cover_file_id)
        if m:
            cover_url = public_media_url(m.file_key)

    return {
        "data": {
            "product": _serialize_product_row(
                product,
                category.name if category else None,
                int(uc or 0),
                cover_url,
            ),
        }
    }
