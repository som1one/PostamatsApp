from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.models.enums import VerificationStatus
from backend.models.media_file import MediaFile
from backend.models.payment import Payment
from backend.models.rental import Rental
from backend.models.user import User
from backend.models.verification_request import VerificationRequest
from backend.routers.admin.auth import get_current_admin
from backend.utils.admin_audit import record_admin_audit
from backend.utils.document_numbers import normalize_document_number
from backend.schemas.admin_panel_schemas import AdminBlockUserPayload, AdminRejectVerificationPayload
from backend.utils.phone_utils import normalize_phone_for_storage
from backend.utils.products_utils import public_media_url

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


def _parse_user_id_param(user_id: str) -> UUID:
    try:
        return UUID(str(user_id).strip())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Некорректный идентификатор пользователя",
        ) from None


def _escape_like_pattern(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _user_search_clause(q: str):
    stripped = q.strip()
    if not stripped:
        return None
    pattern = f"%{_escape_like_pattern(stripped)}%"
    clauses: list = [
        User.phone.ilike(pattern, escape="\\"),
        User.email.ilike(pattern, escape="\\"),
    ]
    digits = "".join(ch for ch in stripped if ch.isdigit())
    if len(digits) >= 4:
        digit_pattern = f"%{_escape_like_pattern(digits)}%"
        clauses.append(User.phone.ilike(digit_pattern, escape="\\"))
    try:
        normalized_phone = normalize_phone_for_storage(stripped)
    except ValueError:
        normalized_phone = None
    if normalized_phone and normalized_phone != stripped:
        npattern = f"%{_escape_like_pattern(normalized_phone)}%"
        clauses.append(User.phone.ilike(npattern, escape="\\"))
    try:
        normalized_document = normalize_document_number(stripped)
    except ValueError:
        normalized_document = None
    if normalized_document:
        clauses.append(
            User.id.in_(
                select(VerificationRequest.user_id).where(
                    VerificationRequest.document_number.ilike(
                        f"%{_escape_like_pattern(normalized_document)}%",
                        escape="\\",
                    )
                )
            )
        )
    return or_(*clauses)


def serialize_admin_user_row(user: User, city_name: str | None) -> dict:
    full_name = " ".join(
        part for part in (user.first_name, user.last_name) if part
    ).strip()
    return {
        "id": str(user.id),
        "phone": user.phone,
        "email": user.email,
        "name": full_name or "Без имени",
        "preferredCityName": city_name,
        "verificationStatus": user.verification_status.value,
        "isBlocked": user.is_blocked,
        "createdAt": user.created_at.isoformat(),
        "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def _serialize_date(d: date | None) -> str | None:
    if d is None:
        return None
    return d.isoformat()


def _serialize_verification(
    vr: VerificationRequest,
    media_by_id: dict[UUID, MediaFile],
) -> dict:
    def file_url(file_id: UUID | None) -> str | None:
        if file_id is None:
            return None
        media = media_by_id.get(file_id)
        if not media:
            return None
        return public_media_url(media.file_key)

    return {
        "id": str(vr.id),
        "status": vr.status.value,
        "documentType": vr.document_type.value,
        "documentNumber": vr.document_number,
        "documentIssueDate": _serialize_date(vr.document_issue_date),
        "documentExpiryDate": _serialize_date(vr.document_expiry_date),
        "rejectReason": vr.reject_reason,
        "reviewedAt": vr.reviewed_at.isoformat() if vr.reviewed_at else None,
        "createdAt": vr.created_at.isoformat(),
        "frontUrl": file_url(vr.front_file_id),
        "backUrl": file_url(vr.back_file_id),
        "selfieUrl": file_url(vr.selfie_file_id),
    }


def _serialize_rental(r: Rental) -> dict:
    return {
        "id": str(r.id),
        "status": r.status.value,
        "createdAt": r.created_at.isoformat(),
        "plannedEndAt": r.planned_end_at.isoformat(),
        "actualEndAt": r.actual_end_at.isoformat() if r.actual_end_at else None,
        "completedAt": r.completed_at.isoformat() if r.completed_at else None,
    }


def _serialize_payment(p: Payment) -> dict:
    amount = p.amount
    if isinstance(amount, Decimal):
        amount = float(amount)
    return {
        "id": str(p.id),
        "status": p.status.value,
        "type": p.type.value,
        "amount": amount,
        "currency": p.currency,
        "createdAt": p.created_at.isoformat(),
        "processedAt": p.processed_at.isoformat() if p.processed_at else None,
    }


async def _get_pending_verification(db: AsyncSession, user_id: UUID) -> VerificationRequest | None:
    stmt = (
        select(VerificationRequest)
        .where(
            VerificationRequest.user_id == user_id,
            VerificationRequest.status == VerificationStatus.PENDING_REVIEW,
        )
        .order_by(VerificationRequest.created_at.desc())
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


async def _get_current_verification(db: AsyncSession, user_id: UUID) -> VerificationRequest | None:
    pending = await _get_pending_verification(db, user_id)
    if pending:
        return pending
    stmt = (
        select(VerificationRequest)
        .where(VerificationRequest.user_id == user_id)
        .order_by(VerificationRequest.created_at.desc())
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


async def _load_media_map(db: AsyncSession, vr: VerificationRequest | None) -> dict[UUID, MediaFile]:
    if not vr:
        return {}
    ids = [fid for fid in (vr.front_file_id, vr.back_file_id, vr.selfie_file_id) if fid]
    if not ids:
        return {}
    files = (await db.scalars(select(MediaFile).where(MediaFile.id.in_(ids)))).all()
    return {m.id: m for m in files}


def _serialize_user_profile(user: User, city_name: str | None) -> dict:
    full_name = " ".join(
        part for part in (user.first_name, user.last_name) if part
    ).strip()
    return {
        "id": str(user.id),
        "phone": user.phone,
        "email": user.email,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "middleName": user.middle_name,
        "name": full_name or "Без имени",
        "birthDate": _serialize_date(user.birth_date),
        "preferredCityName": city_name,
        "verificationStatus": user.verification_status.value,
        "isBlocked": user.is_blocked,
        "blockedReason": user.blocked_reason,
        "createdAt": user.created_at.isoformat(),
        "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.get("")
async def list_admin_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    q: str | None = Query(
        default=None,
        min_length=1,
        max_length=128,
        description="Подстрока телефона или email",
    ),
    verification_status: VerificationStatus | None = Query(
        default=None,
        alias="verificationStatus",
        description="Фильтр по статусу верификации",
    ),
    is_blocked: bool | None = Query(
        default=None,
        alias="isBlocked",
        description="Только заблокированные (true) или незаблокированные (false)",
    ),
):
    await get_current_admin(request, db)

    search = _user_search_clause(q) if q else None
    count_stmt = select(func.count(User.id))
    stmt = select(User).order_by(User.created_at.desc())

    if search is not None:
        count_stmt = count_stmt.where(search)
        stmt = stmt.where(search)
    if verification_status is not None:
        count_stmt = count_stmt.where(User.verification_status == verification_status)
        stmt = stmt.where(User.verification_status == verification_status)
    if is_blocked is not None:
        count_stmt = count_stmt.where(User.is_blocked == is_blocked)
        stmt = stmt.where(User.is_blocked == is_blocked)

    total = await db.scalar(count_stmt) or 0
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    users = (await db.scalars(stmt)).all()

    city_ids = [user.preferred_city_id for user in users if user.preferred_city_id]
    city_map: dict = {}
    if city_ids:
        cities = (await db.scalars(select(City).where(City.id.in_(city_ids)))).all()
        city_map = {city.id: city.name for city in cities}

    return {
        "data": {
            "users": [
                serialize_admin_user_row(user, city_map.get(user.preferred_city_id))
                for user in users
            ]
        },
        "meta": {"page": page, "limit": limit, "total": int(total)},
    }


@router.get("/{user_id}")
async def get_admin_user(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    uid = _parse_user_id_param(user_id)
    user = (
        await db.execute(select(User).where(User.id == uid))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    city_name = None
    if user.preferred_city_id:
        city = await db.get(City, user.preferred_city_id)
        if city:
            city_name = city.name

    vr = await _get_current_verification(db, uid)
    media_map = await _load_media_map(db, vr)
    verification_payload = _serialize_verification(vr, media_map) if vr else None

    rentals = (
        await db.scalars(
            select(Rental)
            .where(Rental.user_id == uid)
            .order_by(Rental.created_at.desc())
            .limit(10)
        )
    ).all()

    payments = (
        await db.scalars(
            select(Payment)
            .where(Payment.user_id == uid)
            .order_by(Payment.created_at.desc())
            .limit(10)
        )
    ).all()

    return {
        "data": {
            "user": _serialize_user_profile(user, city_name),
            "verification": verification_payload,
            "rentals": [_serialize_rental(r) for r in rentals],
            "payments": [_serialize_payment(p) for p in payments],
        }
    }


@router.post("/{user_id}/approve-verification")
async def approve_verification(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)

    uid = _parse_user_id_param(user_id)
    user = (
        await db.execute(select(User).where(User.id == uid))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    vr = await _get_pending_verification(db, uid)
    if not vr:
        raise HTTPException(status_code=400, detail="Нет заявки в статусе ожидания проверки")

    now = datetime.now(timezone.utc)
    vr.status = VerificationStatus.APPROVED
    vr.reviewed_at = now
    vr.reject_reason = None
    user.verification_status = VerificationStatus.APPROVED
    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="user.approve_verification",
            request=request,
            resource_type="user",
            resource_id=uid,
            payload={"verificationRequestId": str(vr.id)},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {"data": {"message": "Верификация подтверждена"}}


@router.post("/{user_id}/reject-verification")
async def reject_verification(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    payload: AdminRejectVerificationPayload = Body(...),
):
    admin, _ = await get_current_admin(request, db)

    uid = _parse_user_id_param(user_id)
    user = (
        await db.execute(select(User).where(User.id == uid))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    vr = await _get_pending_verification(db, uid)
    if not vr:
        raise HTTPException(status_code=400, detail="Нет заявки в статусе ожидания проверки")

    now = datetime.now(timezone.utc)
    vr.status = VerificationStatus.REJECTED
    vr.reject_reason = payload.reason.strip()
    vr.reviewed_at = now
    user.verification_status = VerificationStatus.REJECTED
    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="user.reject_verification",
            request=request,
            resource_type="user",
            resource_id=uid,
            payload={"verificationRequestId": str(vr.id), "reason": vr.reject_reason},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {"data": {"message": "Верификация отклонена"}}


@router.post("/{user_id}/block")
async def block_user(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    payload: AdminBlockUserPayload | None = Body(default=None),
):
    admin, _ = await get_current_admin(request, db)

    uid = _parse_user_id_param(user_id)
    user = (
        await db.execute(select(User).where(User.id == uid))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    user.is_blocked = True
    reason = payload.reason.strip() if payload and payload.reason else ""
    if reason:
        user.blocked_reason = reason
    try:
        record_admin_audit(
            db,
            admin_account_id=admin.id,
            action="user.block",
            request=request,
            resource_type="user",
            resource_id=uid,
            payload={"reason": reason or None},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {"data": {"message": "Пользователь заблокирован"}}
