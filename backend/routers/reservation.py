from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.settings import settings
from backend.models.enums import (
    InventoryStatus,
    LockerStatus,
    PaymentStatus,
    PaymentType,
    RentalEventSource,
    RentalStatus,
    ReservationStatus,
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
from backend.schemas.reservation_schemas import (
    ConfirmReservationPayload,
    CreateReservationPayload,
    ReservationQuotePayload,
)
from backend.utils.auth_utils import get_current_client_user
from backend.utils.lockers_utils import (
    LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY,
    price_plan_to_minor_units,
)
from backend.utils.products_utils import find_price_plan, load_media_files_by_ids, public_media_url
from backend.utils.esi_client import EsiReserveError, reserve_pickup_cell
from backend.utils.reservation_utils import (
    calculate_expires_at,
    calculate_planned_end_at,
    ensure_reservable_user,
    ensure_utc,
    generate_pickup_pin,
)

router = APIRouter(prefix="/reservations", tags=["reservation"])


async def _get_current_user(request: Request, db: AsyncSession) -> User:
    return await get_current_client_user(request, db)


async def _get_product(product_id: UUID, db: AsyncSession) -> Product:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    if not product.is_active:
        raise HTTPException(status_code=410, detail="PRODUCT_INACTIVE")
    return product


async def _get_locker(locker_id: UUID, db: AsyncSession) -> LockerLocation:
    locker = await db.get(LockerLocation, locker_id)
    if not locker:
        raise HTTPException(status_code=404, detail="LOCKER_NOT_FOUND")
    if locker.status != LockerStatus.ONLINE:
        raise HTTPException(status_code=409, detail="LOCKER_OFFLINE")
    return locker


async def _get_price_plan(
    product_id: UUID,
    duration_type: str,
    duration_value: int,
    db: AsyncSession,
) -> PricePlan:
    plan = await find_price_plan(db, product_id, duration_type, duration_value)
    if plan is None:
        raise HTTPException(status_code=404, detail="PRICE_PLAN_NOT_FOUND")
    return plan


async def _get_available_inventory_unit(
    locker_id: UUID,
    product_id: UUID,
    db: AsyncSession,
) -> InventoryUnit | None:
    stmt = (
        select(InventoryUnit)
        .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
        .where(
            LockerCell.locker_id == locker_id,
            InventoryUnit.product_id == product_id,
            InventoryUnit.status == InventoryStatus.AVAILABLE,
            LockerCell.status.not_in(LOCKER_CELL_STATUSES_BLOCKING_AVAILABILITY),
        )
        .order_by(InventoryUnit.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return (await db.scalars(stmt)).first()


async def _ensure_no_active_reservation(user_id: UUID, db: AsyncSession) -> None:
    stmt = select(Reservation).where(
        Reservation.user_id == user_id,
        Reservation.status.in_(
            (
                ReservationStatus.CREATED,
                ReservationStatus.AWAITING_PAYMENT,
                ReservationStatus.PAYMENT_AUTHORIZED,
            )
        ),
    )
    active_reservation = (await db.scalars(stmt.limit(1))).first()
    if active_reservation is not None:
        raise HTTPException(status_code=409, detail="ACTIVE_RESERVATION_EXISTS")


async def _get_reservation_for_user(
    reservation_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> Reservation:
    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status_code=404, detail="RESERVATION_NOT_FOUND")
    if reservation.user_id != user_id:
        raise HTTPException(status_code=403, detail="RESERVATION_FORBIDDEN")
    return reservation


@router.post("/quote")
async def create_quote(
    request: Request,
    payload: ReservationQuotePayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_current_user(request, db)
    ensure_reservable_user(user)

    await _get_product(payload.productId, db)
    await _get_locker(payload.lockerId, db)
    plan = await _get_price_plan(payload.productId, payload.durationType, payload.durationValue, db)

    try:
        unit = await _get_available_inventory_unit(payload.lockerId, payload.productId, db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="RESERVATION_QUOTE_FAILED") from exc

    if unit is None:
        raise HTTPException(status_code=409, detail="PRODUCT_NOT_AVAILABLE")

    quoted_amount = price_plan_to_minor_units(plan.base_amount, plan.currency)
    return {
        "data": {
            "quote": {
                "productId": str(payload.productId),
                "lockerId": str(payload.lockerId),
                "durationType": payload.durationType,
                "durationValue": payload.durationValue,
                "currency": plan.currency,
                "quotedAmount": quoted_amount,
                "preauthAmount": quoted_amount,
                "expiresIn": settings.RESERVATION_QUOTE_EXPIRES_SECONDS,
            }
        }
    }


@router.post("")
async def create_reservation(
    request: Request,
    payload: CreateReservationPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_current_user(request, db)
    ensure_reservable_user(user)

    now = datetime.now(timezone.utc)

    try:
        await _ensure_no_active_reservation(user.id, db)
        await _get_product(payload.productId, db)
        await _get_locker(payload.lockerId, db)
        plan = await _get_price_plan(payload.productId, payload.durationType, payload.durationValue, db)
        unit = await _get_available_inventory_unit(payload.lockerId, payload.productId, db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="RESERVATION_CREATE_FAILED") from exc

    if unit is None:
        raise HTTPException(status_code=409, detail="PRODUCT_NOT_AVAILABLE")

    quoted_amount_minor = price_plan_to_minor_units(plan.base_amount, plan.currency)
    reservation = Reservation(
        user_id=user.id,
        product_id=payload.productId,
        inventory_unit_id=unit.id,
        locker_id=payload.lockerId,
        price_plan_id=plan.id,
        status=ReservationStatus.AWAITING_PAYMENT,
        duration_type=payload.durationType,
        duration_value=payload.durationValue,
        quoted_amount=plan.base_amount,
        preauth_amount=plan.base_amount,
        expires_at=calculate_expires_at(now, payload.pickupWindowMinutes),
    )
    unit.status = InventoryStatus.RESERVED
    db.add(reservation)

    try:
        await db.commit()
        await db.refresh(reservation)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="RESERVATION_CREATE_FAILED") from exc

    return {
        "data": {
            "reservation": {
                "id": str(reservation.id),
                "status": reservation.status.value,
                "productId": str(reservation.product_id),
                "inventoryUnitId": str(reservation.inventory_unit_id),
                "lockerId": str(reservation.locker_id),
                "durationType": reservation.duration_type,
                "durationValue": reservation.duration_value,
                "quotedAmount": quoted_amount_minor,
                "preauthAmount": quoted_amount_minor,
                "expiresAt": ensure_utc(reservation.expires_at).isoformat(),
            }
        }
    }


@router.get("/{reservation_id}")
async def get_reservation(
    reservation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_current_user(request, db)
    reservation = await _get_reservation_for_user(reservation_id, user.id, db)

    try:
        product = await db.get(Product, reservation.product_id)
        locker = await db.get(LockerLocation, reservation.locker_id)
        plan = await db.get(PricePlan, reservation.price_plan_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="RESERVATION_FETCH_FAILED") from exc

    cover_url = None
    if product and product.cover_file_id:
        media_map = await load_media_files_by_ids(db, [product.cover_file_id])
        media = media_map.get(product.cover_file_id)
        if media is not None:
            cover_url = public_media_url(media.file_key)

    return {
        "data": {
            "reservation": {
                "id": str(reservation.id),
                "status": reservation.status.value,
                "expiresAt": ensure_utc(reservation.expires_at).isoformat(),
                "product": {
                    "id": str(product.id) if product else str(reservation.product_id),
                    "name": product.name if product else None,
                    "coverUrl": cover_url,
                },
                "locker": {
                    "id": str(locker.id) if locker else str(reservation.locker_id),
                    "name": locker.name if locker else None,
                    "address": locker.address if locker else None,
                },
                "pricing": {
                    "quotedAmount": price_plan_to_minor_units(
                        reservation.quoted_amount, plan.currency if plan else "RUB"
                    ),
                    "preauthAmount": price_plan_to_minor_units(
                        reservation.preauth_amount or reservation.quoted_amount,
                        plan.currency if plan else "RUB",
                    ),
                    "currency": plan.currency if plan else "RUB",
                },
            }
        }
    }


@router.post("/{reservation_id}/confirm")
async def confirm_reservation(
    reservation_id: UUID,
    request: Request,
    payload: ConfirmReservationPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_current_user(request, db)
    reservation = await _get_reservation_for_user(reservation_id, user.id, db)

    existing_rental = (
        await db.scalars(select(Rental).where(Rental.reservation_id == reservation.id).limit(1))
    ).first()
    if existing_rental is not None:
        return {
            "data": {
                "rental": {
                    "id": str(existing_rental.id),
                    "status": existing_rental.status.value,
                    "pickupPin": existing_rental.pickup_pin,
                    "pickupLockerId": str(existing_rental.pickup_locker_id),
                    "plannedEndAt": ensure_utc(existing_rental.planned_end_at).isoformat(),
                }
            }
        }

    if reservation.status not in (
        ReservationStatus.AWAITING_PAYMENT,
        ReservationStatus.PAYMENT_AUTHORIZED,
    ):
        raise HTTPException(status_code=409, detail="RESERVATION_NOT_CONFIRMABLE")

    payment = await db.get(Payment, payload.paymentId)
    if payment is None or payment.reservation_id != reservation.id or payment.user_id != user.id:
        raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")
    if payment.type != PaymentType.PREAUTH or payment.status != PaymentStatus.AUTHORIZED:
        raise HTTPException(status_code=409, detail="PAYMENT_NOT_AUTHORIZED")

    locker = await db.get(LockerLocation, reservation.locker_id)
    if locker is None:
        raise HTTPException(status_code=404, detail="LOCKER_NOT_FOUND")
    if locker.status != LockerStatus.ONLINE:
        raise HTTPException(status_code=409, detail="LOCKER_OFFLINE")

    now = datetime.now(timezone.utc)
    if ensure_utc(reservation.expires_at) <= now:
        inventory_unit = await db.get(InventoryUnit, reservation.inventory_unit_id)
        if inventory_unit is not None and inventory_unit.status == InventoryStatus.RESERVED:
            inventory_unit.status = InventoryStatus.AVAILABLE
        reservation.status = ReservationStatus.EXPIRED
        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail="RESERVATION_CONFIRM_FAILED") from exc
        raise HTTPException(status_code=409, detail="RESERVATION_EXPIRED")

    try:
        await reserve_pickup_cell(
            db,
            locker_id=reservation.locker_id,
            inventory_unit_id=reservation.inventory_unit_id,
            reservation_id=reservation.id,
        )
    except EsiReserveError as exc:
        await db.rollback()
        # Единица инвентаря остаётся RESERVED: клиент может повторить confirm после починки ESI.
        raise HTTPException(status_code=502, detail="ESI_RESERVE_FAILED") from exc

    rental = Rental(
        user_id=user.id,
        reservation_id=reservation.id,
        inventory_unit_id=reservation.inventory_unit_id,
        pickup_locker_id=reservation.locker_id,
        pickup_pin=generate_pickup_pin(),
        status=RentalStatus.PICKUP_READY,
        planned_end_at=calculate_planned_end_at(
            now,
            reservation.duration_type,
            reservation.duration_value,
        ),
    )
    reservation.status = ReservationStatus.CONFIRMED
    reservation.confirmed_at = now
    db.add(rental)

    try:
        await db.flush()
        rental_event = RentalEvent(
            rental_id=rental.id,
            event_type="reservation_confirmed",
            from_status=None,
            to_status=RentalStatus.PICKUP_READY,
            source=RentalEventSource.USER,
            payload_json={
                "reservationId": str(reservation.id),
                "paymentId": str(payment.id),
            },
        )
        db.add(rental_event)
        await db.commit()
        await db.refresh(rental)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="RESERVATION_CONFIRM_FAILED") from exc

    return {
        "data": {
            "rental": {
                "id": str(rental.id),
                "status": rental.status.value,
                "pickupPin": rental.pickup_pin,
                "pickupLockerId": str(rental.pickup_locker_id),
                "plannedEndAt": ensure_utc(rental.planned_end_at).isoformat(),
            }
        }
    }
