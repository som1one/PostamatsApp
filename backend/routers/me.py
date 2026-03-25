from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.enums import VerificationStatus
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

router = APIRouter(prefix="/me", tags=["me"])


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
