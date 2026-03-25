from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from backend.core.database import get_db
from backend.models.city import City
from backend.utils.cities_utils import serialize_city

router = APIRouter(prefix="/cities", tags=["cities"])


@router.get("/")
async def get_cities(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.scalars(
            select(City)
            .where(City.is_active.is_(True))
            .order_by(City.sort_order.asc(), City.name.asc())
        )
        cities = result.all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "data": {
            "cities": [serialize_city(city) for city in cities],
        }
    }
