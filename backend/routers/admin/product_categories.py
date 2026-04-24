from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.product_category import ProductCategory
from backend.routers.admin.auth import get_current_admin
from backend.routers.admin.cities import normalize_slug
from backend.schemas.admin_panel_schemas import AdminCreateProductCategoryPayload
from backend.utils.admin_audit import record_admin_audit

router = APIRouter(prefix="/api/admin/product-categories", tags=["admin-product-categories"])


@router.get("")
async def list_product_categories(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)
    rows = (
        await db.scalars(
            select(ProductCategory).order_by(ProductCategory.sort_order.asc(), ProductCategory.name.asc())
        )
    ).all()
    return {
        "data": {
            "categories": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "slug": c.slug,
                    "sortOrder": c.sort_order,
                    "isActive": c.is_active,
                }
                for c in rows
            ]
        },
        "meta": {"total": len(rows)},
    }


@router.post("")
async def create_product_category(
    request: Request,
    payload: AdminCreateProductCategoryPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    name = payload.name.strip()
    slug = normalize_slug(payload.slug)
    if not name:
        raise HTTPException(status_code=422, detail="Название обязательно")
    if not slug:
        raise HTTPException(status_code=422, detail="Slug должен содержать латиницу или цифры")

    dup = await db.scalar(select(ProductCategory.id).where(ProductCategory.slug == slug))
    if dup is not None:
        raise HTTPException(status_code=409, detail="Категория с таким slug уже есть")

    cat = ProductCategory(
        name=name,
        slug=slug,
        sort_order=payload.sortOrder,
        is_active=payload.isActive,
    )
    db.add(cat)
    try:
        await db.flush()
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="product_category.create",
            request=request,
            resource_type="product_category",
            resource_id=cat.id,
            payload={"name": cat.name, "slug": cat.slug},
        )
        await db.commit()
        await db.refresh(cat)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось создать категорию") from exc

    return {
        "data": {
            "category": {
                "id": str(cat.id),
                "name": cat.name,
                "slug": cat.slug,
                "sortOrder": cat.sort_order,
                "isActive": cat.is_active,
            }
        }
    }
