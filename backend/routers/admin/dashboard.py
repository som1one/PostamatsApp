from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.locker_location import LockerLocation
from backend.models.user import User
from backend.routers.admin.auth import get_current_admin
from backend.utils.admin_scope import franchise_city_id, user_in_city_clause


router = APIRouter(prefix="/api/admin/dashboard", tags=["admin-dashboard"])


def _day_expression(db: AsyncSession):
    """Группировка по дню. `date_trunc` есть только в Postgres, dev-база — sqlite."""

    try:
        dialect_name = db.get_bind().dialect.name
    except Exception:
        dialect_name = "postgresql"
    if dialect_name == "postgresql":
        return func.date_trunc("day", User.created_at)
    return func.date(User.created_at)


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@router.get("/overview")
async def get_dashboard_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    scope_city_id = franchise_city_id(admin)

    # Франшиза считает только свой город: пользователей города, его
    # постаматы и сам город как единицу географии.
    user_filters = [user_in_city_clause(scope_city_id)] if scope_city_id else []
    locker_filters = (
        [LockerLocation.city_id == scope_city_id] if scope_city_id else []
    )
    city_filters = [City.id == scope_city_id] if scope_city_id else []

    total_users = await db.scalar(select(func.count(User.id)).where(*user_filters)) or 0
    total_cities = await db.scalar(select(func.count(City.id)).where(*city_filters)) or 0
    total_lockers = (
        await db.scalar(select(func.count(LockerLocation.id)).where(*locker_filters)) or 0
    )

    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=13)
    start_datetime = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)

    growth_stmt = (
        select(
            _day_expression(db).label("period_start"),
            func.count(User.id).label("created_count"),
        )
        .where(User.created_at >= start_datetime, *user_filters)
        .group_by("period_start")
        .order_by("period_start")
    )
    growth_rows = (await db.execute(growth_stmt)).all()
    growth_by_day = {}
    for row in growth_rows:
        day = _as_date(row.period_start)
        if day is not None:
            growth_by_day[day] = int(row.created_count)

    user_growth = []
    for offset in range(14):
        current_date = start_date + timedelta(days=offset)
        user_growth.append(
            {
                "date": current_date.isoformat(),
                "label": current_date.strftime("%d.%m"),
                "count": growth_by_day.get(current_date, 0),
            }
        )

    return {
        "data": {
            "metrics": {
                "users": int(total_users),
                "cities": int(total_cities),
                "lockers": int(total_lockers),
                "newUsersLast14Days": sum(item["count"] for item in user_growth),
            },
            "userGrowth": user_growth,
        }
    }
