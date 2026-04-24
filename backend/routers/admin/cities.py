import re
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.db.cities import delete_city_by_id
from backend.models.city import City
from backend.models.locker_location import LockerLocation
from backend.models.user import User
from backend.routers.admin.auth import get_current_admin
from backend.utils.admin_audit import record_admin_audit
from backend.schemas.admin_panel_schemas import AdminCreateCityPayload, AdminUpdateCityPayload
from backend.utils.cities_utils import serialize_admin_city_list_item, serialize_city

router = APIRouter(prefix="/api/admin/cities", tags=["admin-cities"])

SLUG_PATTERN = re.compile(r"[^a-z0-9-]+")


def normalize_slug(raw_slug: str) -> str:
    normalized = SLUG_PATTERN.sub("-", raw_slug.strip().lower()).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized


async def _locker_counts_by_city(db: AsyncSession, city_ids: list[UUID]) -> dict[UUID, int]:
    if not city_ids:
        return {}
    stmt = (
        select(LockerLocation.city_id, func.count(LockerLocation.id))
        .where(LockerLocation.city_id.in_(city_ids))
        .group_by(LockerLocation.city_id)
    )
    rows = await db.execute(stmt)
    return {row[0]: int(row[1]) for row in rows}


@router.get("")
async def list_admin_cities(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    cities = (
        await db.scalars(
            select(City).order_by(City.sort_order.asc(), City.name.asc())
        )
    ).all()
    counts = await _locker_counts_by_city(db, [c.id for c in cities])

    return {
        "data": {
            "cities": [
                serialize_admin_city_list_item(city, locker_count=counts.get(city.id, 0))
                for city in cities
            ]
        },
        "meta": {"total": len(cities)},
    }


@router.get("/{city_id}")
async def get_admin_city(
    request: Request,
    city_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    city = (
        await db.execute(select(City).where(City.id == city_id))
    ).scalar_one_or_none()
    if city is None:
        raise HTTPException(status_code=404, detail="Город не найден")

    locker_count = await db.scalar(
        select(func.count()).select_from(LockerLocation).where(LockerLocation.city_id == city_id)
    ) or 0

    users_with_city = await db.scalar(
        select(func.count()).select_from(User).where(User.preferred_city_id == city_id)
    ) or 0

    lockers = (
        await db.scalars(
            select(LockerLocation)
            .where(LockerLocation.city_id == city_id)
            .order_by(LockerLocation.name.asc())
            .limit(50)
        )
    ).all()

    lockers_payload = [
        {
            "id": str(loc.id),
            "name": loc.name,
            "address": loc.address,
            "status": loc.status.value,
        }
        for loc in lockers
    ]

    base = serialize_city(city)
    base["createdAt"] = city.created_at.isoformat()
    base["updatedAt"] = city.updated_at.isoformat()
    base["lockerCount"] = int(locker_count)
    base["usersWithPreferredCityCount"] = int(users_with_city)

    return {"data": {"city": base, "lockers": lockers_payload}}


@router.post("")
async def create_admin_city(
    request: Request,
    payload: AdminCreateCityPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    normalized_name = payload.name.strip()
    normalized_timezone = payload.timezone.strip()
    normalized_slug = normalize_slug(payload.slug)

    if not normalized_name:
        raise HTTPException(status_code=422, detail="Название города обязательно")
    if not normalized_timezone:
        raise HTTPException(status_code=422, detail="Часовой пояс обязателен")
    if not normalized_slug:
        raise HTTPException(status_code=422, detail="Slug должен содержать латиницу или цифры")

    existing_city = await db.scalar(select(City).where(City.slug == normalized_slug))
    if existing_city is not None:
        raise HTTPException(status_code=409, detail="Город с таким slug уже существует")

    city = City(
        name=normalized_name,
        slug=normalized_slug,
        timezone=normalized_timezone,
        is_active=payload.isActive,
        sort_order=payload.sortOrder,
    )
    db.add(city)

    try:
        await db.flush()
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="city.create",
            request=request,
            resource_type="city",
            resource_id=city.id,
            payload={"name": city.name, "slug": city.slug},
        )
        await db.commit()
        await db.refresh(city)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось создать город") from exc

    return {"data": {"city": serialize_city(city)}}


@router.patch("/{city_id}")
async def update_admin_city(
    request: Request,
    city_id: UUID,
    payload: AdminUpdateCityPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    city = (
        await db.execute(select(City).where(City.id == city_id))
    ).scalar_one_or_none()
    if city is None:
        raise HTTPException(status_code=404, detail="Город не найден")

    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"] is not None:
        name = data["name"].strip()
        if not name:
            raise HTTPException(status_code=422, detail="Название не может быть пустым")
        city.name = name

    if "timezone" in data and data["timezone"] is not None:
        tz = data["timezone"].strip()
        if not tz:
            raise HTTPException(status_code=422, detail="Часовой пояс не может быть пустым")
        city.timezone = tz

    if "slug" in data and data["slug"] is not None:
        normalized_slug = normalize_slug(data["slug"])
        if not normalized_slug:
            raise HTTPException(status_code=422, detail="Slug должен содержать латиницу или цифры")
        conflict = await db.scalar(
            select(City.id).where(City.slug == normalized_slug, City.id != city_id)
        )
        if conflict is not None:
            raise HTTPException(status_code=409, detail="Город с таким slug уже существует")
        city.slug = normalized_slug

    if "isActive" in data:
        city.is_active = data["isActive"]

    if "sortOrder" in data:
        city.sort_order = data["sortOrder"]

    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="city.update",
            request=request,
            resource_type="city",
            resource_id=city_id,
            payload={"fields": list(data.keys())},
        )
        await db.commit()
        await db.refresh(city)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось обновить город") from exc

    return {"data": {"city": serialize_city(city)}}


async def _perform_admin_city_delete(
    request: Request,
    city_id: UUID,
    db: AsyncSession,
) -> dict:
    admin, _ = await get_current_admin(request, db)

    outcome = await delete_city_by_id(db, city_id)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Город не найден")
    if outcome == "has_lockers":
        raise HTTPException(
            status_code=409,
            detail="Нельзя удалить город, пока к нему привязаны постаматы",
        )

    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="city.delete",
            request=request,
            resource_type="city",
            resource_id=city_id,
            payload=None,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось удалить город") from exc

    return {"data": {"deleted": True, "cityId": str(city_id)}}


@router.delete("/{city_id}")
async def delete_admin_city(
    request: Request,
    city_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await _perform_admin_city_delete(request, city_id, db)


@router.post("/{city_id}/delete")
async def delete_admin_city_post(
    request: Request,
    city_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """То же, что DELETE: POST нужен, если прокси режет DELETE (часто даёт 404)."""
    return await _perform_admin_city_delete(request, city_id, db)
