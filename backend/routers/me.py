from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.enums import (
    DocumentType,
    InventoryStatus,
    LockerCellStatus,
    PaymentStatus,
    RentalEventSource,
    RentalStatus,
    ReservationStatus,
    ReturnRequestStatus,
    VerificationStatus,
)
from backend.models.payment import Payment
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.models.return_request import ReturnRequest
from backend.models.user import User
from backend.models.verification_request import VerificationRequest
from backend.utils.esi_client import EsiOpenError, admin_trigger_open_cell
from backend.utils.inventory_tracking import add_inventory_movement
from backend.utils.return_requests import (
    complete_return_request,
    get_active_return_request_for_rental,
)
from backend.schemas.me_schemas import (
    CreateVerificationRequest,
    DeleteVerificationRequest,
    RentalReturnRequestPayload,
    UpdateMePayload,
)
from backend.utils.auth_utils import get_current_client_user
from backend.utils.document_numbers import normalize_document_number
from backend.utils.yookassa_service import cancel_yookassa_payment
from backend.utils.me_utils import (
    UPDATE_ME_FIELD_MAP,
    VerificationFileResolveError,
    normalize_email,
    resolve_verification_file_ids,
    serialize_user,
    serialize_verification_not_started,
    serialize_verification_request,
)
from backend.utils.products_utils import load_media_files_by_ids, public_media_url
from backend.utils.rental_return_flow import ReturnRequestError, start_rental_return
from backend.utils.rental_serialization import serialize_rental_detail, serialize_rental_list_item
from backend.utils.reservation_utils import ensure_utc

router = APIRouter(prefix="/me", tags=["me"])

_RETURN_REQUEST_ERRORS: dict[str, tuple[int, str]] = {
    "INVALID_RENTAL_STATUS": (409, "INVALID_RENTAL_STATUS"),
    "RETURN_ALREADY_IN_PROGRESS": (409, "RETURN_ALREADY_IN_PROGRESS"),
    "LOCKER_NOT_FOUND": (404, "LOCKER_NOT_FOUND"),
    "LOCKER_OFFLINE": (409, "LOCKER_OFFLINE"),
    "RETURN_LOCKER_DIFFERENT_CITY": (409, "RETURN_LOCKER_DIFFERENT_CITY"),
    "RETURN_CELL_NOT_AVAILABLE": (409, "RETURN_CELL_NOT_AVAILABLE"),
    "INVENTORY_NOT_FOUND": (500, "RETURN_REQUEST_FAILED"),
    "ESI_OPEN_FAILED": (502, "ESI_OPEN_FAILED"),
    "ESI_NOT_CONFIGURED": (503, "ESI_NOT_CONFIGURED"),
    "RETURN_CELL_NOT_FOUND": (502, "ESI_OPEN_FAILED"),
    "RETURN_CELL_NOT_OPERABLE": (409, "RETURN_CELL_NOT_OPERABLE"),
    "RETURN_REQUEST_FAILED": (500, "RETURN_REQUEST_FAILED"),
}

_RENTAL_STATUS_GROUPS: dict[str, tuple[RentalStatus, ...]] = {
    "active": (
        RentalStatus.PICKUP_READY,
        RentalStatus.PICKUP_OPENED,
        RentalStatus.ACTIVE,
        RentalStatus.RETURN_IN_PROGRESS,
        RentalStatus.OVERDUE,
    ),
    "completed": (RentalStatus.COMPLETED,),
    "cancelled": (RentalStatus.CANCELLED, RentalStatus.INCIDENT),
}

_UPCOMING_RESERVATION_STATUSES: tuple[ReservationStatus, ...] = (
    ReservationStatus.CREATED,
    ReservationStatus.AWAITING_PAYMENT,
    ReservationStatus.PAYMENT_AUTHORIZED,
)


@router.get("")
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_client_user(request, db)

    return {
        "data": {
            "user": serialize_user(user),
        }
    }


@router.patch("")
async def update_me(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: UpdateMePayload = Body(...),
):
    user = await get_current_client_user(request, db)

    try:
        payload_dict = payload.model_dump(exclude_none=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid payload") from exc

    email = payload_dict.get("email")
    if email is not None:
        normalized_email = normalize_email(email)
        result = await db.execute(
            select(User).where(
                User.email == normalized_email,
                User.id != user.id,
            )
        )
        existing_user = result.scalar_one_or_none()
        if existing_user is not None:
            raise HTTPException(status_code=409, detail="Email is already in use")
        payload_dict["email"] = normalized_email

    for api_key, value in payload_dict.items():
        model_key = UPDATE_ME_FIELD_MAP.get(api_key, api_key)
        if hasattr(user, model_key):
            setattr(user, model_key, value)

    try:
        await db.commit()
        await db.refresh(user)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update user") from exc

    return {"data": {"user": serialize_user(user)}}


@router.post("/verification")
async def create_verification_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: CreateVerificationRequest = Body(...),
):
    user = await get_current_client_user(request, db)

    if user.verification_status == VerificationStatus.APPROVED:
        raise HTTPException(status_code=400, detail="User is already verified")

    if user.verification_status == VerificationStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Verification request already in review")

    document_name = (payload.documentName or "").strip() or None
    if payload.documentType == DocumentType.OTHER and not document_name:
        raise HTTPException(status_code=400, detail="DOCUMENT_NAME_REQUIRED")

    try:
        document_number = normalize_document_number(payload.documentNumber)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_request = (
        await db.execute(
            select(VerificationRequest).where(
                VerificationRequest.document_number == document_number
            )
        )
    ).scalar_one_or_none()
    if existing_request is not None:
        raise HTTPException(status_code=409, detail="DOCUMENT_NUMBER_ALREADY_EXISTS")

    try:
        front_id, back_id, selfie_id = await resolve_verification_file_ids(
            db, user.id, payload.files
        )
    except VerificationFileResolveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user.first_name = payload.firstName
    user.last_name = payload.lastName
    user.birth_date = payload.birthDate
    user.verification_status = VerificationStatus.PENDING_REVIEW

    verification_request = VerificationRequest(
        user_id=user.id,
        status=VerificationStatus.PENDING_REVIEW,
        document_type=payload.documentType,
        document_name=document_name,
        document_number=document_number,
        document_issue_date=payload.documentIssueDate,
        document_expiry_date=payload.documentExpiryDate,
        front_file_id=front_id,
        back_file_id=back_id,
        selfie_file_id=selfie_id,
    )
    db.add(verification_request)

    try:
        await db.commit()
        await db.refresh(verification_request)
        await db.refresh(user)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save verification request") from exc

    return {
        "data": {
            "verification": serialize_verification_request(verification_request),
        }
    }


@router.delete("/verification")
async def delete_verification_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: DeleteVerificationRequest = Body(...),
):
    user = await get_current_client_user(request, db)

    try:
        document_number = normalize_document_number(payload.documentNumber)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await db.execute(
        select(VerificationRequest)
        .where(
            VerificationRequest.user_id == user.id,
            VerificationRequest.document_number == document_number,
        )
        .order_by(VerificationRequest.created_at.desc())
        .limit(1)
    )
    verification_request = result.scalar_one_or_none()

    if verification_request is None:
        raise HTTPException(status_code=404, detail="VERIFICATION_REQUEST_NOT_FOUND")

    if verification_request.status == VerificationStatus.APPROVED:
        raise HTTPException(status_code=400, detail="VERIFICATION_ALREADY_APPROVED")

    await db.delete(verification_request)
    user.verification_status = VerificationStatus.DRAFT

    try:
        await db.commit()
        await db.refresh(user)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="FAILED_TO_DELETE_VERIFICATION") from exc

    return {"data": {"verification": serialize_verification_not_started()}}


@router.get("/verification")
async def get_verification_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_client_user(request, db)

    result = await db.execute(
        select(VerificationRequest)
        .where(VerificationRequest.user_id == user.id)
        .order_by(VerificationRequest.created_at.desc())
        .limit(1)
    )
    verification_request = result.scalar_one_or_none()

    if verification_request is None:
        return {"data": {"verification": serialize_verification_not_started()}}

    return {
        "data": {
            "verification": serialize_verification_request(verification_request),
        }
    }


@router.get("/reservations")
async def list_my_reservations(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_client_user(request, db)

    stmt = (
        select(Reservation)
        .where(
            Reservation.user_id == user.id,
            Reservation.status.in_(_UPCOMING_RESERVATION_STATUSES),
        )
        .order_by(Reservation.created_at.desc())
    )
    reservations = (await db.scalars(stmt)).all()

    if not reservations:
        return {"data": {"reservations": []}}

    product_ids = list({reservation.product_id for reservation in reservations})
    products = (
        (await db.scalars(select(Product).where(Product.id.in_(product_ids)))).all()
        if product_ids
        else []
    )
    product_by_id = {product.id: product for product in products}

    locker_ids = list({reservation.locker_id for reservation in reservations})
    lockers = (
        (await db.scalars(select(LockerLocation).where(LockerLocation.id.in_(locker_ids)))).all()
        if locker_ids
        else []
    )
    locker_by_id = {locker.id: locker for locker in lockers}

    cover_ids = [product.cover_file_id for product in products if product.cover_file_id]
    media_by_id = await load_media_files_by_ids(db, cover_ids) if cover_ids else {}

    items: list[dict] = []
    for reservation in reservations:
        product = product_by_id.get(reservation.product_id)
        locker = locker_by_id.get(reservation.locker_id)
        cover_url = None
        if product is not None and product.cover_file_id:
            media = media_by_id.get(product.cover_file_id)
            if media is not None:
                cover_url = public_media_url(media.file_key)

        items.append(
            {
                "id": str(reservation.id),
                "status": reservation.status.value,
                "expiresAt": ensure_utc(reservation.expires_at).isoformat(),
                "product": {
                    "id": str(product.id) if product is not None else str(reservation.product_id),
                    "name": product.name if product is not None else None,
                    "coverUrl": cover_url,
                },
                "locker": {
                    "id": str(locker.id) if locker is not None else str(reservation.locker_id),
                    "name": locker.name if locker is not None else None,
                    "address": locker.address if locker is not None else None,
                },
            }
        )

    return {"data": {"reservations": items}}


@router.post("/reservations/{reservation_id}/cancel")
async def cancel_my_reservation(
    reservation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_client_user(request, db)

    reservation = (
        await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    ).scalar_one_or_none()
    if reservation is None:
        raise HTTPException(status_code=404, detail="RESERVATION_NOT_FOUND")
    if reservation.user_id != user.id:
        raise HTTPException(status_code=403, detail="RESERVATION_FORBIDDEN")

    cancellable_statuses = (
        ReservationStatus.CREATED,
        ReservationStatus.AWAITING_PAYMENT,
        ReservationStatus.PAYMENT_AUTHORIZED,
    )
    if reservation.status not in cancellable_statuses:
        raise HTTPException(status_code=409, detail="RESERVATION_NOT_CANCELLABLE")

    now = datetime.now(timezone.utc)

    # Если платёж уже авторизован — сначала отменяем его в Юкасса
    payment_id: UUID | None = None
    provider_payment_id: str | None = None
    if reservation.status == ReservationStatus.PAYMENT_AUTHORIZED:
        payment_row = (
            await db.execute(
                select(Payment.id, Payment.provider_payment_id)
                .where(
                    Payment.reservation_id == reservation.id,
                    Payment.status.in_(("AUTHORIZED", "authorized")),
                    Payment.type.in_(("PREAUTH", "preauth")),
                )
                .limit(1)
            )
        ).first()
        if payment_row is not None:
            payment_id, provider_payment_id = payment_row
        if provider_payment_id:
            try:
                await cancel_yookassa_payment(provider_payment_id)
            except Exception as exc:
                raise HTTPException(
                    status_code=502, detail="YOOKASSA_CANCEL_FAILED"
                ) from exc

    try:
        if payment_id is not None:
            await db.execute(
                update(Payment)
                .where(Payment.id == payment_id)
                .values(status=PaymentStatus.CANCELLED, processed_at=now)
            )

        await db.execute(
            update(InventoryUnit)
            .where(InventoryUnit.id == reservation.inventory_unit_id)
            .values(status=InventoryStatus.AVAILABLE)
        )

        await db.execute(
            update(Reservation)
            .where(Reservation.id == reservation.id)
            .values(
                status=ReservationStatus.CANCELLED,
                cancelled_at=now,
                cancel_reason="cancelled_by_user",
            )
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="RESERVATION_CANCEL_FAILED") from exc

    return {
        "data": {
            "reservation": {
                "id": str(reservation.id),
                "status": ReservationStatus.CANCELLED.value,
                "cancelledAt": now.isoformat(),
            }
        }
    }


@router.get("/rentals")
async def list_my_rentals(
    request: Request,
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    user = await get_current_client_user(request, db)

    filters = [Rental.user_id == user.id]
    if status is not None and status != "":
        group = _RENTAL_STATUS_GROUPS.get(status)
        if group is None:
            raise HTTPException(status_code=400, detail="INVALID_STATUS_FILTER")
        filters.append(Rental.status.in_(group))

    total = (
        await db.scalar(select(func.count()).select_from(Rental).where(*filters)) or 0
    )

    stmt = (
        select(Rental)
        .where(*filters)
        .order_by(Rental.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rentals = (await db.scalars(stmt)).all()

    if not rentals:
        return {
            "data": {"rentals": []},
            "meta": {"page": page, "limit": limit, "total": total},
        }

    unit_ids = [r.inventory_unit_id for r in rentals]
    units = (
        (await db.scalars(select(InventoryUnit).where(InventoryUnit.id.in_(unit_ids)))).all()
        if unit_ids
        else []
    )
    unit_by_id = {u.id: u for u in units}
    product_ids = [u.product_id for u in units if u.product_id]
    products = (
        (await db.scalars(select(Product).where(Product.id.in_(product_ids)))).all()
        if product_ids
        else []
    )
    prod_by_id = {p.id: p for p in products}
    locker_ids = list({r.pickup_locker_id for r in rentals})
    lockers = (
        (await db.scalars(select(LockerLocation).where(LockerLocation.id.in_(locker_ids)))).all()
        if locker_ids
        else []
    )
    locker_by_id = {loc.id: loc for loc in lockers}

    items = []
    for r in rentals:
        unit = unit_by_id.get(r.inventory_unit_id)
        prod = prod_by_id.get(unit.product_id) if unit else None
        loc = locker_by_id.get(r.pickup_locker_id)
        items.append(await serialize_rental_list_item(db, r, prod, loc))

    return {
        "data": {"rentals": items},
        "meta": {"page": page, "limit": limit, "total": total},
    }


@router.get("/rentals/{rental_id}")
async def get_my_rental(
    rental_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_client_user(request, db)

    rental = (
        await db.execute(select(Rental).where(Rental.id == rental_id))
    ).scalar_one_or_none()
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    if rental.user_id != user.id:
        raise HTTPException(status_code=403, detail="RENTAL_FORBIDDEN")

    detail = await serialize_rental_detail(db, rental)
    return {"data": detail}


@router.post("/rentals/{rental_id}/return-request")
async def request_rental_return(
    rental_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: RentalReturnRequestPayload = Body(default_factory=RentalReturnRequestPayload),
):
    user = await get_current_client_user(request, db)

    rental = (
        await db.execute(select(Rental).where(Rental.id == rental_id))
    ).scalar_one_or_none()
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    if rental.user_id != user.id:
        raise HTTPException(status_code=403, detail="RENTAL_FORBIDDEN")

    return_locker_id = payload.lockerId or rental.return_locker_id or rental.pickup_locker_id

    try:
        result = await start_rental_return(db, rental=rental, return_locker_id=return_locker_id)
    except ReturnRequestError as exc:
        mapped = _RETURN_REQUEST_ERRORS.get(
            exc.code,
            (500, "RETURN_REQUEST_FAILED"),
        )
        raise HTTPException(status_code=mapped[0], detail=mapped[1]) from exc

    return {"data": {"return": result}}


@router.post("/rentals/{rental_id}/open-cell")
async def open_pickup_cell(
    rental_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Открывает ячейку постамата для получения товара клиентом.

    Доступно владельцу аренды в статусах PICKUP_READY/PICKUP_OPENED.
    Триггерит команду открытия в ESI (или dev-stub) и помечает аренду
    PICKUP_OPENED. Реальное событие забора (transition в ACTIVE) приходит
    позднее веб-хуком от постамата.
    """
    user = await get_current_client_user(request, db)

    rental = (
        await db.execute(select(Rental).where(Rental.id == rental_id))
    ).scalar_one_or_none()
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    if rental.user_id != user.id:
        raise HTTPException(status_code=403, detail="RENTAL_FORBIDDEN")

    if rental.status not in (RentalStatus.PICKUP_READY, RentalStatus.PICKUP_OPENED):
        raise HTTPException(status_code=409, detail="RENTAL_NOT_PICKUP_READY")

    inventory_unit = await db.get(InventoryUnit, rental.inventory_unit_id)
    if inventory_unit is None or inventory_unit.locker_cell_id is None:
        raise HTTPException(status_code=409, detail="INVENTORY_CELL_MISSING")

    cell = await db.get(LockerCell, inventory_unit.locker_cell_id)
    if cell is None:
        raise HTTPException(status_code=409, detail="INVENTORY_CELL_MISSING")

    locker_id = rental.pickup_locker_id

    # Командуем постамату открыть ячейку через ESI. Если железо недоступно
    # (офлайн / нет связи / API ругается), возвращаем понятную ошибку, а не
    # молча "успех". Статус rental в этом случае не меняется.
    try:
        await admin_trigger_open_cell(
            db, locker_id=locker_id, cell_id=cell.id
        )
    except EsiOpenError as exc:
        code = str(exc) or "ESI_OPEN_FAILED"
        if code == "ESI_MACHINE_OFFLINE":
            raise HTTPException(status_code=503, detail="LOCKER_OFFLINE") from exc
        if code == "ESI_NOT_CONFIGURED":
            raise HTTPException(status_code=503, detail="LOCKER_NOT_CONFIGURED") from exc
        if code == "CELL_NOT_OPERABLE":
            raise HTTPException(status_code=409, detail="CELL_NOT_OPERABLE") from exc
        raise HTTPException(status_code=502, detail="ESI_OPEN_FAILED") from exc

    now = datetime.now(timezone.utc)
    if rental.status == RentalStatus.PICKUP_READY:
        prev_status = rental.status
        rental.status = RentalStatus.PICKUP_OPENED
        db.add(
            RentalEvent(
                rental_id=rental.id,
                event_type="pickup_cell_opened",
                from_status=prev_status,
                to_status=RentalStatus.PICKUP_OPENED,
                source=RentalEventSource.USER,
                payload_json={"trigger": "client_open_cell"},
            )
        )

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="OPEN_CELL_FAILED") from exc

    return {
        "data": {
            "rental": {
                "id": str(rental.id),
                "status": rental.status.value,
            }
        }
    }


@router.post("/rentals/{rental_id}/confirm-pickup")
async def confirm_pickup(
    rental_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Подтверждает, что клиент забрал товар.

    Используется после `open-cell`, когда у нас нет реального ESI-вебхука
    о закрытии ячейки (dev-режим, флаки железа). Переводит rental из
    PICKUP_OPENED/PICKUP_READY в ACTIVE и фиксирует, что инвентарь уехал
    из постамата.
    """
    user = await get_current_client_user(request, db)

    rental = await db.get(Rental, rental_id)
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    if rental.user_id != user.id:
        raise HTTPException(status_code=403, detail="RENTAL_FORBIDDEN")

    if rental.status == RentalStatus.ACTIVE:
        return {
            "data": {
                "rental": {
                    "id": str(rental.id),
                    "status": rental.status.value,
                }
            }
        }
    if rental.status not in (RentalStatus.PICKUP_READY, RentalStatus.PICKUP_OPENED):
        raise HTTPException(status_code=409, detail="RENTAL_NOT_PICKUP_READY")

    now = datetime.now(timezone.utc)
    unit = await db.get(InventoryUnit, rental.inventory_unit_id)
    cell = (
        await db.get(LockerCell, unit.locker_cell_id)
        if unit is not None and unit.locker_cell_id is not None
        else None
    )

    prev_rental_status = rental.status
    prev_unit_status = unit.status if unit is not None else None
    prev_cell_id = unit.locker_cell_id if unit is not None else None

    rental.status = RentalStatus.ACTIVE
    rental.starts_at = rental.starts_at or now

    if unit is not None:
        unit.status = InventoryStatus.RENTED
        unit.locker_cell_id = None

    if cell is not None:
        cell.status = LockerCellStatus.VACANT
        cell.last_closed_at = now
        cell.last_event_at = now

    if unit is not None:
        add_inventory_movement(
            db,
            unit=unit,
            from_locker_id=rental.pickup_locker_id,
            to_locker_id=None,
            from_cell_id=prev_cell_id,
            to_cell_id=None,
            from_status=prev_unit_status,
            to_status=InventoryStatus.RENTED,
            reason="pickup_confirmed_by_user",
        )

    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type="pickup_completed",
            from_status=prev_rental_status,
            to_status=RentalStatus.ACTIVE,
            source=RentalEventSource.USER,
            payload_json={"trigger": "client_confirm_pickup"},
        )
    )

    try:
        await db.commit()
        await db.refresh(rental)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="CONFIRM_PICKUP_FAILED") from exc

    return {
        "data": {
            "rental": {
                "id": str(rental.id),
                "status": rental.status.value,
            }
        }
    }


@router.post("/rentals/{rental_id}/confirm-return")
async def confirm_return(
    rental_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Подтверждает, что клиент уже положил товар в выбранный постамат.

    Используется после `return-request`, когда у нас нет реального ESI
    вебхука `return_cell_closed`. Переводит rental в COMPLETED и
    return-request в COMPLETED через ту же утилиту, что и автоматический
    обработчик железа.
    """
    user = await get_current_client_user(request, db)

    rental = await db.get(Rental, rental_id)
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    if rental.user_id != user.id:
        raise HTTPException(status_code=403, detail="RENTAL_FORBIDDEN")

    if rental.status == RentalStatus.COMPLETED:
        return {
            "data": {
                "rental": {
                    "id": str(rental.id),
                    "status": rental.status.value,
                }
            }
        }
    if rental.status != RentalStatus.RETURN_IN_PROGRESS:
        raise HTTPException(status_code=409, detail="RENTAL_NOT_RETURNING")

    return_request = await get_active_return_request_for_rental(db, rental.id)
    if return_request is None:
        raise HTTPException(status_code=409, detail="RETURN_REQUEST_NOT_FOUND")

    if return_request.status not in (
        ReturnRequestStatus.CREATED,
        ReturnRequestStatus.LOCKER_OPENED,
        ReturnRequestStatus.AWAITING_CLOSE,
    ):
        raise HTTPException(status_code=409, detail="RETURN_REQUEST_NOT_ACTIVE")

    try:
        completed_rental, _unit = await complete_return_request(
            db,
            request=return_request,
            provider_event_id=None,
            source=RentalEventSource.USER,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # Логируем полный traceback, иначе наружу видно только generic 500
        # и невозможно понять, что именно упало в complete_return_request.
        import logging

        logging.getLogger(__name__).exception("confirm-return failed")
        raise HTTPException(status_code=500, detail="CONFIRM_RETURN_FAILED") from exc

    if completed_rental is None:
        raise HTTPException(status_code=500, detail="CONFIRM_RETURN_FAILED")

    return {
        "data": {
            "rental": {
                "id": str(completed_rental.id),
                "status": completed_rental.status.value,
            }
        }
    }
