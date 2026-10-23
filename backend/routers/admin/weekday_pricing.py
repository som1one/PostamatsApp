from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.product import Product
from backend.models.weekday_price_markup import WeekdayPriceMarkup
from backend.routers.admin.auth import get_current_admin
from backend.schemas.admin_panel_schemas import AdminWeekdayMarkupsPayload
from backend.utils.admin_audit import record_admin_audit
from backend.utils.admin_scope import require_full_access_admin
from backend.utils.rental_pricing import (
    WEEKDAY_MARKUP_MAX_PERCENT,
    WEEKDAY_MARKUP_MIN_PERCENT,
    load_weekday_markups,
)

router = APIRouter(
    prefix="/api/admin/weekday-pricing",
    tags=["admin-weekday-pricing"],
    # Цены общие для всей сети, как и каталог, — франшизе не показываем.
    dependencies=[Depends(require_full_access_admin)],
)

WEEKDAY_NAMES = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


async def _serialize(db: AsyncSession) -> dict:
    enabled_count = await db.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.weekday_pricing_enabled.is_(True))
    )
    return {
        "markups": list(await load_weekday_markups(db)),
        "minPercent": WEEKDAY_MARKUP_MIN_PERCENT,
        "maxPercent": WEEKDAY_MARKUP_MAX_PERCENT,
        "enabledProductCount": int(enabled_count or 0),
    }


@router.get("")
async def get_weekday_pricing(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)
    return {"data": await _serialize(db)}


@router.put("")
async def update_weekday_pricing(
    request: Request,
    payload: AdminWeekdayMarkupsPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    for weekday, percent in enumerate(payload.markups):
        if not WEEKDAY_MARKUP_MIN_PERCENT <= percent <= WEEKDAY_MARKUP_MAX_PERCENT:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Наценка на {WEEKDAY_NAMES[weekday]} должна быть от "
                    f"{WEEKDAY_MARKUP_MIN_PERCENT} до {WEEKDAY_MARKUP_MAX_PERCENT}%"
                ),
            )

    previous = list(await load_weekday_markups(db))
    rows = {row.weekday: row for row in (await db.scalars(select(WeekdayPriceMarkup))).all()}
    for weekday, percent in enumerate(payload.markups):
        row = rows.get(weekday)
        if row is None:
            db.add(WeekdayPriceMarkup(weekday=weekday, percent=percent))
        else:
            row.percent = percent

    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="pricing.weekday_markups.update",
            request=request,
            resource_type="weekday_pricing",
            payload={"previous": previous, "markups": list(payload.markups)},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось сохранить наценки") from exc

    return {"data": await _serialize(db)}
