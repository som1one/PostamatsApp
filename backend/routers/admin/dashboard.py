from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.locker_location import LockerLocation
from backend.models.user import User
from backend.routers.admin.auth import get_current_admin


router = APIRouter(prefix="/api/admin/dashboard", tags=["admin-dashboard"])


@router.get("/overview")
async def get_dashboard_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    total_users = await db.scalar(select(func.count(User.id))) or 0
    total_cities = await db.scalar(select(func.count(City.id))) or 0
    total_lockers = await db.scalar(select(func.count(LockerLocation.id))) or 0

    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=13)
    start_datetime = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)

    growth_stmt = (
        select(
            func.date_trunc("day", User.created_at).label("period_start"),
            func.count(User.id).label("created_count"),
        )
        .where(User.created_at >= start_datetime)
        .group_by("period_start")
        .order_by("period_start")
    )
    growth_rows = (await db.execute(growth_stmt)).all()
    growth_by_day = {
        row.period_start.date(): int(row.created_count)
        for row in growth_rows
        if row.period_start is not None
    }

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
