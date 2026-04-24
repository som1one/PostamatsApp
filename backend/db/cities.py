from typing import Literal
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.city import City
from backend.models.locker_location import LockerLocation
from backend.models.user import User

DeleteCityOutcome = Literal["deleted", "not_found", "has_lockers"]


async def delete_city_by_id(session: AsyncSession, city_id: UUID) -> DeleteCityOutcome:
    city = (
        await session.execute(select(City).where(City.id == city_id))
    ).scalar_one_or_none()
    if city is None:
        return "not_found"

    locker_count = await session.scalar(
        select(func.count()).select_from(LockerLocation).where(LockerLocation.city_id == city_id)
    )
    if (locker_count or 0) > 0:
        return "has_lockers"

    await session.execute(
        update(User).where(User.preferred_city_id == city_id).values(preferred_city_id=None)
    )
    await session.execute(delete(City).where(City.id == city_id))
    return "deleted"
