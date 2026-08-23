"""Ограничение доступа админов-франчайзи их городами.

Правила:

* ``super_admin`` и ``operator`` видят всю сеть — для них скоуп ``None``;
* ``franchise`` видит только объекты своих городов (связка
  ``admin_account_cities``, один город или несколько): постаматы, ячейки,
  аренды, пользователей и верификации этих городов;
* разделы «Города», «Каталог», «Обратная связь», «Аудит» и управление франшизами
  франчайзи недоступны совсем.

Скоуп везде — это ``list[UUID] | None``: ``None`` означает «вся сеть», а
список никогда не бывает пустым (пустой у франшизы — это 403, иначе
фильтр `IN ()` молча показал бы всё).

Модуль намеренно не знает про FastAPI-зависимости: роутеры сначала
получают админа через ``get_current_admin``, а затем зовут хелперы отсюда.
"""

from __future__ import annotations

from typing import Iterable, Sequence
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.admin_account import AdminAccount
from backend.models.enums import AdminRole
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.rental import Rental
from backend.models.reservation import Reservation
from backend.models.user import User

SECTION_FORBIDDEN_DETAIL = "Раздел недоступен для франшизы"
CITY_FORBIDDEN_DETAIL = "Объект относится к другому городу"
CITY_NOT_SET_DETAIL = "У франшизы не заданы города — обратитесь к администратору"


def is_franchise(admin: AdminAccount) -> bool:
    return admin.role == AdminRole.FRANCHISE


def franchise_city_ids(admin: AdminAccount) -> list[UUID] | None:
    """Города, которыми ограничен админ. ``None`` — доступ ко всей сети."""

    if not is_franchise(admin):
        return None
    city_ids = [city.id for city in admin.cities]
    if not city_ids:
        raise HTTPException(status_code=403, detail=CITY_NOT_SET_DETAIL)
    return city_ids


def _as_city_list(city_ids: Iterable[UUID] | UUID) -> list[UUID]:
    """Позволяет звать хелперы и с одним городом, и со списком."""

    if isinstance(city_ids, UUID):
        return [city_ids]
    return list(city_ids)


def require_not_franchise(admin: AdminAccount) -> None:
    """Раздел скрыт от франшизы целиком (города, каталог, обратная связь, аудит)."""

    if is_franchise(admin):
        raise HTTPException(status_code=403, detail=SECTION_FORBIDDEN_DETAIL)


def require_super_admin(admin: AdminAccount) -> None:
    """Только владелец сети: управление франшизами."""

    if admin.role != AdminRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")


def ensure_city_in_scope(
    scope_city_ids: Sequence[UUID] | None, city_id: UUID | None
) -> None:
    """Проверяет, что объект указанного города доступен админу."""

    if scope_city_ids is None:
        return
    if city_id is None:
        raise HTTPException(status_code=403, detail=CITY_FORBIDDEN_DETAIL)
    allowed = {str(value) for value in scope_city_ids}
    if str(city_id) not in allowed:
        raise HTTPException(status_code=403, detail=CITY_FORBIDDEN_DETAIL)


def user_in_city_clause(city_ids: Iterable[UUID] | UUID):
    """Пользователь «принадлежит» городу, если выбрал его как основной
    либо оформлял бронь/аренду в постамате этого города.

    Аренды и брони учитываем специально: без них франшиза не увидела бы
    карточку и верификацию клиента, который приехал из другого города,
    но берёт вещь в её постамате. Принимает как один город, так и список —
    у франшизы городов может быть несколько.
    """

    cities = _as_city_list(city_ids)
    rentals_in_city = (
        select(Rental.user_id)
        .join(LockerLocation, Rental.pickup_locker_id == LockerLocation.id)
        .where(LockerLocation.city_id.in_(cities))
    )
    reservations_in_city = (
        select(Reservation.user_id)
        .join(LockerLocation, Reservation.locker_id == LockerLocation.id)
        .where(LockerLocation.city_id.in_(cities))
    )
    return or_(
        User.preferred_city_id.in_(cities),
        User.id.in_(rentals_in_city),
        User.id.in_(reservations_in_city),
    )


async def ensure_user_in_scope(
    db: AsyncSession,
    scope_city_ids: Sequence[UUID] | None,
    user_id: UUID,
) -> None:
    if scope_city_ids is None:
        return
    allowed = await db.scalar(
        select(User.id).where(User.id == user_id, user_in_city_clause(scope_city_ids))
    )
    if allowed is None:
        raise HTTPException(status_code=403, detail=CITY_FORBIDDEN_DETAIL)


async def ensure_locker_in_scope(
    db: AsyncSession,
    scope_city_ids: Sequence[UUID] | None,
    locker: LockerLocation | UUID | None,
) -> None:
    if scope_city_ids is None:
        return
    if locker is None:
        raise HTTPException(status_code=403, detail=CITY_FORBIDDEN_DETAIL)
    if isinstance(locker, LockerLocation):
        ensure_city_in_scope(scope_city_ids, locker.city_id)
        return
    city_id = await db.scalar(
        select(LockerLocation.city_id).where(LockerLocation.id == locker)
    )
    ensure_city_in_scope(scope_city_ids, city_id)


async def ensure_cell_in_scope(
    db: AsyncSession,
    scope_city_ids: Sequence[UUID] | None,
    cell: LockerCell,
) -> None:
    if scope_city_ids is None:
        return
    await ensure_locker_in_scope(db, scope_city_ids, cell.locker_id)


async def ensure_rental_in_scope(
    db: AsyncSession,
    scope_city_ids: Sequence[UUID] | None,
    rental: Rental,
) -> None:
    if scope_city_ids is None:
        return
    await ensure_locker_in_scope(db, scope_city_ids, rental.pickup_locker_id)


async def require_full_access_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AdminAccount:
    """Router-level зависимость для разделов, скрытых от франшизы."""

    # Импорт внутри функции: `routers.admin.auth` тянет утилиты из этого
    # пакета, и импорт на уровне модуля дал бы цикл.
    from backend.routers.admin.auth import get_current_admin

    admin, _ = await get_current_admin(request, db)
    require_not_franchise(admin)
    return admin


__all__ = [
    "CITY_FORBIDDEN_DETAIL",
    "CITY_NOT_SET_DETAIL",
    "SECTION_FORBIDDEN_DETAIL",
    "ensure_cell_in_scope",
    "ensure_city_in_scope",
    "ensure_locker_in_scope",
    "ensure_rental_in_scope",
    "ensure_user_in_scope",
    "franchise_city_ids",
    "is_franchise",
    "require_full_access_admin",
    "require_not_franchise",
    "require_super_admin",
    "user_in_city_clause",
]
