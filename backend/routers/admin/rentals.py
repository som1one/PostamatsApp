from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.condition_report import ConditionReport
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    RentalEventSource,
    RentalStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.payment import Payment
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.models.user import User
from backend.routers.admin.auth import get_current_admin
from backend.utils.admin_audit import record_admin_audit
from backend.utils.admin_scope import ensure_rental_in_scope, franchise_city_ids
from backend.utils.bonus_ledger import accrue_rental_bonus
from backend.utils.lockers_utils import price_plan_to_minor_units
from backend.utils.rental_serialization import rental_is_overdue, serialize_rental_detail

router = APIRouter(prefix="/api/admin/rentals", tags=["admin-rentals"])

_TERMINAL_RENTAL: frozenset[RentalStatus] = frozenset(
    {
        RentalStatus.COMPLETED,
        RentalStatus.CANCELLED,
        RentalStatus.INCIDENT,
    }
)

_NO_CANCEL_RENTAL: frozenset[RentalStatus] = frozenset(
    {
        RentalStatus.COMPLETED,
        RentalStatus.CANCELLED,
    }
)


def _parse_rental_id(rental_id: str) -> UUID:
    try:
        return UUID(str(rental_id).strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный идентификатор аренды") from None


def _user_display_name(user: User) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p).strip() or "Без имени"


def _is_overdue_row(rental: Rental, now: datetime) -> bool:
    # Одна и та же формула нужна и в списке аренд, и в карточке пользователя,
    # поэтому живёт в utils, а не тут.
    return rental_is_overdue(rental, now)


def _minor_units(amount, currency: str | None = "RUB") -> int:
    return price_plan_to_minor_units(amount, currency or "RUB") if amount is not None else 0


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _serialize_rental_user_card(db: AsyncSession, user: User) -> dict:
    """Профиль арендатора прямо в карточке аренды.

    Оператору почти всегда нужно не «кто это», а «можно ли ему доверять»:
    сколько у него аренд, есть ли просрочки, верифицирован ли, не заблокирован.
    Раньше здесь были только имя и телефон, за остальным приходилось уходить
    в раздел пользователей и искать руками.
    """
    city_name = None
    if user.preferred_city_id:
        city = await db.get(City, user.preferred_city_id)
        city_name = city.name if city else None

    counts = (
        await db.execute(
            select(Rental.status, func.count(Rental.id))
            .where(Rental.user_id == user.id)
            .group_by(Rental.status)
        )
    ).all()
    by_status = {status: count for status, count in counts}

    return {
        "id": str(user.id),
        "phone": user.phone,
        "name": _user_display_name(user),
        "email": user.email,
        "cityName": city_name,
        "verificationStatus": user.verification_status.value,
        "isBlocked": user.is_blocked,
        "blockedReason": user.blocked_reason,
        "registeredAt": _iso(user.created_at),
        "lastLoginAt": _iso(user.last_login_at),
        "rentalsTotal": sum(by_status.values()),
        "rentalsCompleted": by_status.get(RentalStatus.COMPLETED, 0),
        "rentalsActive": by_status.get(RentalStatus.ACTIVE, 0)
        + by_status.get(RentalStatus.PICKUP_READY, 0)
        + by_status.get(RentalStatus.PICKUP_OPENED, 0),
        "rentalsOverdue": by_status.get(RentalStatus.OVERDUE, 0),
        "rentalsIncident": by_status.get(RentalStatus.INCIDENT, 0),
    }


async def _serialize_rental_reservation(db: AsyncSession, rental: Rental) -> dict | None:
    """Условия, на которых аренду оформили: срок, дата выдачи, цена."""
    if not rental.reservation_id:
        return None
    res = await db.get(Reservation, rental.reservation_id)
    if res is None:
        return None

    plan = await db.get(PricePlan, res.price_plan_id) if res.price_plan_id else None
    currency = plan.currency if plan else "RUB"
    return {
        "id": str(res.id),
        "status": res.status.value,
        "createdAt": _iso(res.created_at),
        "pickupAt": _iso(res.pickup_at),
        "expiresAt": _iso(res.expires_at),
        "confirmedAt": _iso(res.confirmed_at),
        "cancelledAt": _iso(res.cancelled_at),
        "cancelReason": res.cancel_reason,
        "durationType": res.duration_type,
        "durationValue": res.duration_value,
        "quotedAmount": _minor_units(res.quoted_amount, currency),
        "preauthAmount": _minor_units(res.preauth_amount, currency),
        "currency": currency,
        "pricePlanName": plan.name if plan else None,
    }


async def _serialize_rental_payments(db: AsyncSession, rental: Rental) -> list[dict]:
    """Все платежи по аренде, а не только две суммы в сводке.

    Идентификатор на стороне ЮKassa нужен, чтобы оператор мог за секунду
    найти платёж в личном кабинете — например, когда клиент утверждает, что
    деньги списаны, а у нас платёж висит.
    """
    conditions = []
    if rental.reservation_id:
        conditions.append(Payment.reservation_id == rental.reservation_id)
    conditions.append(Payment.rental_id == rental.id)

    stmt = (
        select(Payment)
        .where(or_(*conditions))
        .order_by(Payment.created_at.asc())
    )
    return [
        {
            "id": str(p.id),
            "providerPaymentId": p.provider_payment_id,
            "type": p.type.value,
            "status": p.status.value,
            "amount": _minor_units(p.amount, p.currency),
            "currency": p.currency,
            "createdAt": _iso(p.created_at),
            "processedAt": _iso(p.processed_at),
            "failureCode": p.failure_code,
            "failureMessage": p.failure_message,
        }
        for p in (await db.scalars(stmt)).all()
    ]


async def _serialize_rental_cell(db: AsyncSession, unit: InventoryUnit | None) -> dict | None:
    if unit is None or unit.locker_cell_id is None:
        return None
    cell = await db.get(LockerCell, unit.locker_cell_id)
    if cell is None:
        return None
    return {
        "id": str(cell.id),
        "label": cell.label,
        "externalCellId": cell.external_cell_id,
        "status": cell.status.value,
        "supportsReturn": cell.supports_return,
    }


async def _release_unit_and_cell(db: AsyncSession, rental: Rental) -> None:
    unit = await db.get(InventoryUnit, rental.inventory_unit_id)
    if unit is not None:
        if unit.status in (
            InventoryStatus.RESERVED,
            InventoryStatus.RENTED,
            InventoryStatus.RETURN_PENDING,
        ):
            unit.status = InventoryStatus.AVAILABLE
        if unit.locker_cell_id is not None:
            cell = await db.get(LockerCell, unit.locker_cell_id)
            if cell is not None and cell.status == LockerCellStatus.RESERVED:
                cell.status = LockerCellStatus.VACANT


@router.get("")
async def list_rentals(
    request: Request,
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None),
    city_id: UUID | None = Query(None),
    locker_id: UUID | None = Query(None),
    overdue_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    admin, _ = await get_current_admin(request, db)
    scope_city_ids = franchise_city_ids(admin)

    filters: list = []
    if status:
        try:
            st = RentalStatus(status.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_STATUS_FILTER") from None
        filters.append(Rental.status == st)

    if scope_city_ids is not None:
        # Город франшизы жёстче любого фильтра из запроса.
        filters.append(LockerLocation.city_id.in_(scope_city_ids))
    elif city_id is not None:
        filters.append(LockerLocation.city_id == city_id)

    if locker_id is not None:
        filters.append(
            or_(
                Rental.pickup_locker_id == locker_id,
                Rental.return_locker_id == locker_id,
            )
        )

    now = datetime.now(timezone.utc)
    if overdue_only:
        filters.append(
            or_(
                Rental.status == RentalStatus.OVERDUE,
                (Rental.status == RentalStatus.ACTIVE) & (Rental.planned_end_at < now),
            )
        )

    count_stmt = (
        select(func.count(Rental.id))
        .select_from(Rental)
        .join(User, Rental.user_id == User.id)
        .join(InventoryUnit, Rental.inventory_unit_id == InventoryUnit.id)
        .join(Product, InventoryUnit.product_id == Product.id)
        .join(LockerLocation, Rental.pickup_locker_id == LockerLocation.id)
        .join(City, LockerLocation.city_id == City.id)
        .where(*filters)
    )
    total = (await db.scalar(count_stmt)) or 0

    stmt = (
        select(Rental, User, Product, LockerLocation, City)
        .join(User, Rental.user_id == User.id)
        .join(InventoryUnit, Rental.inventory_unit_id == InventoryUnit.id)
        .join(Product, InventoryUnit.product_id == Product.id)
        .join(LockerLocation, Rental.pickup_locker_id == LockerLocation.id)
        .join(City, LockerLocation.city_id == City.id)
        .where(*filters)
        .order_by(Rental.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    items = []
    for rental, user, product, locker, city in rows:
        items.append(
            {
                "id": str(rental.id),
                "status": rental.status.value,
                "createdAt": rental.created_at.isoformat(),
                "plannedEndAt": rental.planned_end_at.isoformat(),
                "isOverdue": _is_overdue_row(rental, now),
                "user": {
                    "id": str(user.id),
                    "phone": user.phone,
                    "name": _user_display_name(user),
                },
                "product": {
                    "id": str(product.id),
                    "name": product.name,
                },
                "pickupLocker": {
                    "id": str(locker.id),
                    "name": locker.name,
                    "cityName": city.name,
                },
            }
        )

    return {
        "data": {"rentals": items},
        "meta": {"page": page, "limit": limit, "total": total},
    }


@router.get("/{rental_id}")
async def get_rental(
    rental_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    rid = _parse_rental_id(rental_id)
    rental = await db.get(Rental, rid)
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    await ensure_rental_in_scope(db, franchise_city_ids(admin), rental)

    user = await db.get(User, rental.user_id)
    unit = await db.get(InventoryUnit, rental.inventory_unit_id)
    product = await db.get(Product, unit.product_id) if unit and unit.product_id else None
    return_locker = (
        await db.get(LockerLocation, rental.return_locker_id)
        if rental.return_locker_id
        else None
    )
    pickup_city = None
    pickup_locker = await db.get(LockerLocation, rental.pickup_locker_id)
    if pickup_locker is not None and pickup_locker.city_id:
        city = await db.get(City, pickup_locker.city_id)
        pickup_city = city.name if city else None

    detail = await serialize_rental_detail(db, rental)
    detail["user"] = await _serialize_rental_user_card(db, user) if user else None
    detail["inventoryUnit"] = (
        {
            "id": str(unit.id),
            "status": unit.status.value,
            "serialNumber": unit.serial_number,
            "barcode": unit.barcode,
        }
        if unit
        else None
    )
    detail["productId"] = str(product.id) if product else None
    detail["reservation"] = await _serialize_rental_reservation(db, rental)
    detail["payments"] = await _serialize_rental_payments(db, rental)
    detail["cell"] = await _serialize_rental_cell(db, unit)
    detail["pickupCityName"] = pickup_city
    detail["returnLocker"] = (
        {
            "id": str(return_locker.id),
            "name": return_locker.name,
            "address": return_locker.address,
        }
        if return_locker
        else None
    )
    # Собственные сроки аренды: сводка сверху карточки отвечает на «что с ней
    # сейчас», а эти поля — на «что уже произошло и когда».
    detail["timeline"] = {
        "createdAt": _iso(rental.created_at),
        "pickupExpiresAt": _iso(rental.pickup_expires_at),
        "overdueStartedAt": _iso(rental.overdue_started_at),
        "completedAt": _iso(rental.completed_at),
        "cancelReason": rental.cancel_reason,
        "isOverdue": _is_overdue_row(rental, datetime.now(timezone.utc)),
    }

    return {"data": detail}


@router.post("/{rental_id}/cancel")
async def cancel_rental(
    rental_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    rid = _parse_rental_id(rental_id)
    rental = await db.get(Rental, rid)
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    await ensure_rental_in_scope(db, franchise_city_ids(admin), rental)
    if rental.status in _NO_CANCEL_RENTAL:
        raise HTTPException(status_code=409, detail="RENTAL_NOT_CANCELLABLE")

    prev = rental.status
    now = datetime.now(timezone.utc)
    rental.status = RentalStatus.CANCELLED
    rental.actual_end_at = now
    rental.completed_at = now

    await _release_unit_and_cell(db, rental)

    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type="admin_cancel",
            from_status=prev,
            to_status=RentalStatus.CANCELLED,
            source=RentalEventSource.ADMIN,
            payload_json=None,
        )
    )
    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="rental.cancel",
            request=request,
            resource_type="rental",
            resource_id=rental.id,
            payload={"fromStatus": prev.value},
        )
        await db.commit()
        await db.refresh(rental)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="RENTAL_CANCEL_FAILED") from exc

    return {
        "data": {
            "rental": {
                "id": str(rental.id),
                "status": rental.status.value,
                "actualEndAt": rental.actual_end_at.isoformat() if rental.actual_end_at else None,
                "completedAt": rental.completed_at.isoformat() if rental.completed_at else None,
            }
        }
    }


@router.post("/{rental_id}/force-complete")
async def force_complete_rental(
    rental_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    rid = _parse_rental_id(rental_id)
    rental = await db.get(Rental, rid)
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    await ensure_rental_in_scope(db, franchise_city_ids(admin), rental)
    if rental.status in (RentalStatus.COMPLETED, RentalStatus.CANCELLED):
        raise HTTPException(status_code=409, detail="RENTAL_NOT_FORCE_COMPLETABLE")

    prev = rental.status
    now = datetime.now(timezone.utc)
    rental.status = RentalStatus.COMPLETED
    rental.actual_end_at = now
    rental.completed_at = now

    await _release_unit_and_cell(db, rental)

    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type="admin_force_complete",
            from_status=prev,
            to_status=RentalStatus.COMPLETED,
            source=RentalEventSource.ADMIN,
            payload_json=None,
        )
    )

    # Аренду закрыл оператор, но для клиента она всё равно завершилась —
    # бонусы начисляем так же, как при штатном возврате.
    await accrue_rental_bonus(db, rental=rental)

    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="rental.force_complete",
            request=request,
            resource_type="rental",
            resource_id=rental.id,
            payload={"fromStatus": prev.value},
        )
        await db.commit()
        await db.refresh(rental)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="RENTAL_FORCE_COMPLETE_FAILED") from exc

    return {
        "data": {
            "rental": {
                "id": str(rental.id),
                "status": rental.status.value,
                "actualEndAt": rental.actual_end_at.isoformat() if rental.actual_end_at else None,
                "completedAt": rental.completed_at.isoformat() if rental.completed_at else None,
            }
        }
    }


@router.delete("/{rental_id}")
async def delete_rental(
    rental_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    rid = _parse_rental_id(rental_id)
    rental = await db.get(Rental, rid)
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    await ensure_rental_in_scope(db, franchise_city_ids(admin), rental)
    if rental.status not in _TERMINAL_RENTAL:
        raise HTTPException(status_code=409, detail="RENTAL_NOT_DELETABLE")

    try:
        await db.execute(delete(RentalEvent).where(RentalEvent.rental_id == rid))
        await db.execute(update(Payment).where(Payment.rental_id == rid).values(rental_id=None))
        await db.execute(
            update(ConditionReport).where(ConditionReport.rental_id == rid).values(rental_id=None)
        )
        await db.delete(rental)
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="rental.delete",
            request=request,
            resource_type="rental",
            resource_id=rid,
            payload=None,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="RENTAL_DELETE_FAILED") from exc

    return {"data": {"deleted": True}}
