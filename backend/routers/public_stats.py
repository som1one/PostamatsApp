from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.user import User


router = APIRouter(prefix="/public", tags=["public"])


@router.get("/stats")
async def get_public_stats(db: AsyncSession = Depends(get_db)):
    """Безопасный для публичного доступа набор счётчиков.

    Сейчас отдаёт только число зарегистрированных и неразблокированных
    пользователей — для отображения на главной странице сайта. Никакой
    персональной информации тут не появляется.
    """

    user_count = await db.scalar(
        select(func.count(User.id)).where(User.is_blocked.is_(False))
    )

    return {
        "data": {
            "stats": {
                "users": int(user_count or 0),
            }
        }
    }
