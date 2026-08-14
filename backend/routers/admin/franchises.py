"""Управление франшизами: выдача доступа, блокировка, пароль, статистика.

Раздел доступен только владельцу сети (``super_admin``). Сам франчайзи
входит в ту же админку обычным логином/паролем, но все разделы ему
режутся по городу — см. :mod:`backend.utils.admin_scope`.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.admin_account import AdminAccount
from backend.models.admin_audit_event import AdminAuditEvent
from backend.models.admin_auth_session import AdminAuthSession
from backend.models.city import City
from backend.models.enums import (
    AdminRole,
    LockerCellStatus,
    LockerStatus,
    PaymentStatus,
    RentalStatus,
    VerificationStatus,
)
from backend.models.inventory_movement import InventoryMovement
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.payment import Payment
from backend.models.rental import Rental
from backend.models.user import User
from backend.routers.admin.auth import get_current_admin
from backend.schemas.admin_franchise_schemas import (
    AdminCreateFranchisePayload,
    AdminFranchisePasswordPayload,
    AdminUpdateFranchisePayload,
)
from backend.utils.admin_audit import record_admin_audit
from backend.utils.admin_auth_utils import hash_password
from backend.utils.admin_scope import require_super_admin, user_in_city_clause

router = APIRouter(prefix="/api/admin/franchises", tags=["admin-franchises"])

_ACTIVE_RENTAL_STATUSES = (
    RentalStatus.PICKUP_READY,
    RentalStatus.PICKUP_OPENED,
    RentalStatus.ACTIVE,
    RentalStatus.RETURN_IN_PROGRESS,
)

_STATS_WINDOW_DAYS = 30


def _serialize_franchise(admin: AdminAccount, city: City | None) -> dict:
    return {
        "id": str(admin.id),
        "name": admin.name,
        "login": admin.login,
        "isActive": bool(admin.is_active),
        "cityId": str(admin.city_id) if admin.city_id else None,
        "cityName": city.name if city else None,
        "lastLoginAt": admin.last_login_at.isoformat() if admin.last_login_at else None,
        "createdAt": admin.created_at.isoformat() if admin.created_at else None,
    }


async def _get_franchise(db: AsyncSession, franchise_id: UUID) -> AdminAccount:
    admin = await db.get(AdminAccount, franchise_id)
    if admin is None or admin.role != AdminRole.FRANCHISE:
        raise HTTPException(status_code=404, detail="Франшиза не найдена")
    return admin


async def _get_city(db: AsyncSession, city_id: UUID) -> City:
    city = await db.get(City, city_id)
    if city is None:
        raise HTTPException(status_code=404, detail="Город не найден")
    return city


async def _revoke_sessions(db: AsyncSession, admin_id: UUID, reason: str) -> None:
    await db.execute(
        update(AdminAuthSession)
        .where(
            AdminAuthSession.admin_account_id == admin_id,
            AdminAuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc), revoke_reason=reason)
    )


async def _ensure_login_free(db: AsyncSession, login: str, exclude_id: UUID | None = None) -> None:
    stmt = select(AdminAccount.id).where(AdminAccount.login == login)
    if exclude_id is not None:
        stmt = stmt.where(AdminAccount.id != exclude_id)
    if await db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail="Такой логин уже занят")


@router.get("")
async def list_franchises(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    require_super_admin(admin)

    franchises = (
        await db.scalars(
            select(AdminAccount)
            .where(AdminAccount.role == AdminRole.FRANCHISE)
            .order_by(AdminAccount.name.asc())
        )
    ).all()

    city_ids = [item.city_id for item in franchises if item.city_id]
    city_map: dict[UUID, City] = {}
    if city_ids:
        cities = (await db.scalars(select(City).where(City.id.in_(city_ids)))).all()
        city_map = {city.id: city for city in cities}

    return {
        "data": {
            "franchises": [
                _serialize_franchise(item, city_map.get(item.city_id))
                for item in franchises
            ]
        },
        "meta": {"total": len(franchises)},
    }


@router.post("")
async def create_franchise(
    request: Request,
    payload: AdminCreateFranchisePayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    require_super_admin(admin)

    city = await _get_city(db, payload.cityId)
    await _ensure_login_free(db, payload.login)

    franchise = AdminAccount(
        name=payload.name,
        login=payload.login,
        role=AdminRole.FRANCHISE,
        password_hash=hash_password(payload.password),
        city_id=city.id,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(franchise)

    try:
        await db.flush()
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="franchise.create",
            request=request,
            resource_type="franchise",
            resource_id=franchise.id,
            payload={"login": franchise.login, "cityId": str(city.id)},
        )
        await db.commit()
        await db.refresh(franchise)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось создать франшизу") from exc

    return {"data": {"franchise": _serialize_franchise(franchise, city)}}


@router.patch("/{franchise_id}")
async def update_franchise(
    request: Request,
    franchise_id: UUID,
    payload: AdminUpdateFranchisePayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    require_super_admin(admin)

    franchise = await _get_franchise(db, franchise_id)
    changes: dict[str, object] = {}

    if payload.name is not None and payload.name != franchise.name:
        franchise.name = payload.name
        changes["name"] = payload.name

    city: City | None = None
    if payload.cityId is not None and payload.cityId != franchise.city_id:
        city = await _get_city(db, payload.cityId)
        franchise.city_id = city.id
        changes["cityId"] = str(city.id)
        # Город сменился — старые сессии смотрели на чужие данные.
        await _revoke_sessions(db, franchise.id, "city_changed")

    if payload.isActive is not None and payload.isActive != franchise.is_active:
        franchise.is_active = payload.isActive
        changes["isActive"] = payload.isActive
        if not payload.isActive:
            await _revoke_sessions(db, franchise.id, "access_disabled")

    if city is None and franchise.city_id is not None:
        city = await db.get(City, franchise.city_id)

    if changes:
        try:
            record_admin_audit(
                db,
                admin_account_id=admin.id,
                action="franchise.update",
                request=request,
                resource_type="franchise",
                resource_id=franchise.id,
                payload=changes,
            )
            await db.commit()
            await db.refresh(franchise)
        except Exception as exc:
            await db.rollback()
            raise HTTPException(
                status_code=500, detail="Не удалось обновить франшизу"
            ) from exc

    return {"data": {"franchise": _serialize_franchise(franchise, city)}}


@router.post("/{franchise_id}/password")
async def change_franchise_password(
    request: Request,
    franchise_id: UUID,
    payload: AdminFranchisePasswordPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    require_super_admin(admin)

    franchise = await _get_franchise(db, franchise_id)
    franchise.password_hash = hash_password(payload.password)
    # Смена пароля выкидывает франчайзи из всех устройств.
    await _revoke_sessions(db, franchise.id, "password_changed")

    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="franchise.change_password",
            request=request,
            resource_type="franchise",
            resource_id=franchise.id,
            payload={"login": franchise.login},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось сменить пароль") from exc

    return {"data": {"message": "Пароль обновлён"}}


@router.delete("/{franchise_id}")
async def delete_franchise(
    request: Request,
    franchise_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    require_super_admin(admin)

    franchise = await _get_franchise(db, franchise_id)

    # История действий важнее удобства: аккаунт с активностью только
    # выключаем, иначе каскад снёс бы записи аудита.
    audit_count = (
        await db.scalar(
            select(func.count(AdminAuditEvent.id)).where(
                AdminAuditEvent.admin_account_id == franchise.id
            )
        )
    ) or 0
    movement_count = (
        await db.scalar(
            select(func.count(InventoryMovement.id)).where(
                InventoryMovement.performed_by_admin_id == franchise.id
            )
        )
    ) or 0
    if audit_count or movement_count:
        raise HTTPException(
            status_code=409,
            detail="У франшизы есть история действий — выключите доступ вместо удаления",
        )

    login = franchise.login
    try:
        await db.execute(
            delete(AdminAuthSession).where(
                AdminAuthSession.admin_account_id == franchise.id
            )
        )
        await db.delete(franchise)
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="franchise.delete",
            request=request,
            resource_type="franchise",
            resource_id=franchise_id,
            payload={"login": login},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Не удалось удалить франшизу") from exc

    return {"data": {"deleted": True}}


async def build_city_stats(db: AsyncSession, city_id: UUID) -> dict:
    """Сводка по городу: пользователи, постаматы, аренды, выручка."""

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=_STATS_WINDOW_DAYS)
    user_scope = user_in_city_clause(city_id)

    users_total = (await db.scalar(select(func.count(User.id)).where(user_scope))) or 0
    users_verified = (
        await db.scalar(
            select(func.count(User.id)).where(
                user_scope, User.verification_status == VerificationStatus.APPROVED
            )
        )
    ) or 0
    users_pending = (
        await db.scalar(
            select(func.count(User.id)).where(
                user_scope,
                User.verification_status == VerificationStatus.PENDING_REVIEW,
            )
        )
    ) or 0
    users_blocked = (
        await db.scalar(
            select(func.count(User.id)).where(user_scope, User.is_blocked.is_(True))
        )
    ) or 0
    users_new = (
        await db.scalar(
            select(func.count(User.id)).where(user_scope, User.created_at >= window_start)
        )
    ) or 0

    locker_rows = (
        await db.execute(
            select(LockerLocation.status, func.count(LockerLocation.id))
            .where(LockerLocation.city_id == city_id)
            .group_by(LockerLocation.status)
        )
    ).all()
    lockers_total = sum(int(count) for _, count in locker_rows)
    lockers_online = sum(
        int(count) for status, count in locker_rows if status == LockerStatus.ONLINE
    )

    cell_rows = (
        await db.execute(
            select(LockerCell.status, func.count(LockerCell.id))
            .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
            .where(
                LockerLocation.city_id == city_id,
                LockerCell.status != LockerCellStatus.DISABLED,
            )
            .group_by(LockerCell.status)
        )
    ).all()
    cells_total = sum(int(count) for _, count in cell_rows)
    cells_free = sum(
        int(count) for status, count in cell_rows if status == LockerCellStatus.VACANT
    )
    cells_occupied = sum(
        int(count)
        for status, count in cell_rows
        if status in (LockerCellStatus.OCCUPIED, LockerCellStatus.RESERVED)
    )

    rental_rows = (
        await db.execute(
            select(Rental.status, func.count(Rental.id))
            .join(LockerLocation, Rental.pickup_locker_id == LockerLocation.id)
            .where(LockerLocation.city_id == city_id)
            .group_by(Rental.status)
        )
    ).all()
    rentals_by_status = {status: int(count) for status, count in rental_rows}
    rentals_total = sum(rentals_by_status.values())
    rentals_active = sum(
        rentals_by_status.get(status, 0) for status in _ACTIVE_RENTAL_STATUSES
    )
    rentals_new = (
        await db.scalar(
            select(func.count(Rental.id))
            .join(LockerLocation, Rental.pickup_locker_id == LockerLocation.id)
            .where(LockerLocation.city_id == city_id, Rental.created_at >= window_start)
        )
    ) or 0

    revenue_total = await db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Rental, Payment.rental_id == Rental.id)
        .join(LockerLocation, Rental.pickup_locker_id == LockerLocation.id)
        .where(
            LockerLocation.city_id == city_id,
            Payment.status == PaymentStatus.CAPTURED,
        )
    )
    revenue_window = await db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Rental, Payment.rental_id == Rental.id)
        .join(LockerLocation, Rental.pickup_locker_id == LockerLocation.id)
        .where(
            LockerLocation.city_id == city_id,
            Payment.status == PaymentStatus.CAPTURED,
            func.coalesce(Payment.processed_at, Payment.created_at) >= window_start,
        )
    )

    def _money(value) -> float:
        if isinstance(value, Decimal):
            return float(value)
        return float(value or 0)

    return {
        "windowDays": _STATS_WINDOW_DAYS,
        "users": {
            "total": int(users_total),
            "verified": int(users_verified),
            "pendingVerification": int(users_pending),
            "blocked": int(users_blocked),
            "newInWindow": int(users_new),
        },
        "lockers": {
            "total": lockers_total,
            "online": lockers_online,
            "cellsTotal": cells_total,
            "cellsFree": cells_free,
            "cellsOccupied": cells_occupied,
        },
        "rentals": {
            "total": rentals_total,
            "active": rentals_active,
            "overdue": rentals_by_status.get(RentalStatus.OVERDUE, 0),
            "completed": rentals_by_status.get(RentalStatus.COMPLETED, 0),
            "cancelled": rentals_by_status.get(RentalStatus.CANCELLED, 0),
            "incident": rentals_by_status.get(RentalStatus.INCIDENT, 0),
            "newInWindow": int(rentals_new),
        },
        "revenue": {
            "captured": _money(revenue_total),
            "capturedInWindow": _money(revenue_window),
            "currency": "RUB",
        },
    }


@router.get("/{franchise_id}/stats")
async def get_franchise_stats(
    request: Request,
    franchise_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    require_super_admin(admin)

    franchise = await _get_franchise(db, franchise_id)
    if franchise.city_id is None:
        raise HTTPException(status_code=409, detail="У франшизы не задан город")

    city = await _get_city(db, franchise.city_id)
    stats = await build_city_stats(db, city.id)

    return {
        "data": {
            "franchise": _serialize_franchise(franchise, city),
            "stats": stats,
        }
    }
