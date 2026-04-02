from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.enums import RentalStatus, VerificationStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.rental import Rental
from backend.models.user import User
from backend.models.verification_request import VerificationRequest
from backend.schemas.me_schemas import CreateVerificationRequest, UpdateMePayload
from backend.utils.auth_utils import extract_bearer_token, verify_access_token
from backend.utils.me_utils import (
    UPDATE_ME_FIELD_MAP,
    VerificationFileResolveError,
    normalize_email,
    resolve_verification_file_ids,
    serialize_user,
    serialize_verification_not_started,
    serialize_verification_request,
)
from backend.utils.rental_serialization import serialize_rental_detail, serialize_rental_list_item

router = APIRouter(prefix="/me", tags=["me"])

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


@router.get("")
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    access_token = extract_bearer_token(request)
    session = await verify_access_token(access_token, db)
    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

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
    access_token = extract_bearer_token(request)
    session = await verify_access_token(access_token, db)
    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

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
    access_token = extract_bearer_token(request)
    session = await verify_access_token(access_token, db)
    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if user.verification_status == VerificationStatus.BLOCKED:
        raise HTTPException(status_code=403, detail="User is blocked")

    if user.verification_status == VerificationStatus.APPROVED:
        raise HTTPException(status_code=400, detail="User is already verified")

    if user.verification_status == VerificationStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Verification request already in review")

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
        document_number=payload.documentNumber,
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


@router.get("/verification")
async def get_verification_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    access_token = extract_bearer_token(request)
    session = await verify_access_token(access_token, db)
    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

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


@router.get("/rentals")
async def list_my_rentals(
    request: Request,
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    access_token = extract_bearer_token(request)
    session = await verify_access_token(access_token, db)
    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

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
    access_token = extract_bearer_token(request)
    session = await verify_access_token(access_token, db)
    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    rental = await db.get(Rental, rental_id)
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")
    if rental.user_id != user.id:
        raise HTTPException(status_code=403, detail="RENTAL_FORBIDDEN")

    detail = await serialize_rental_detail(db, rental)
    return {"data": detail}
