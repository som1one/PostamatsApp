from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.settings import settings
from backend.models.auth_session import AuthSession
from backend.models.auth_verification_session import AuthVerificationSession
from backend.models.enums import (
    AuthPlatform,
    AuthVerificationSessionStatus,
    VerificationStatus,
)
from backend.models.user import User
from backend.schemas.auth_schemas import ConfirmCodePayload, RequestCodePayload
from backend.utils.auth_utils import (
    create_access_token,
    create_refresh_token,
    extract_bearer_token,
    generate_code,
    hash_code,
    hash_refresh_token,
    verify_code,
    verify_refresh_token,
    verify_access_token,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_auth_platform(request: Request) -> AuthPlatform:
    platform_name = (request.headers.get("x-platform") or "web").lower()
    try:
        return AuthPlatform(platform_name)
    except ValueError:
        return AuthPlatform.WEB


@router.post("/request-code")
async def request_code(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: RequestCodePayload | None = Body(default=None),
    phone: str | None = Query(default=None),
):
    resolved_phone = payload.phone if payload is not None else phone
    if not resolved_phone:
        raise HTTPException(status_code=422, detail="Phone is required")

    now = datetime.now(timezone.utc)
    code = generate_code()
    hashed_code = hash_code(code)
    verification_session = AuthVerificationSession(
        phone=resolved_phone,
        code_hash=hashed_code,
        expires_at=now + timedelta(seconds=settings.JWT_ACCESS_TOKEN_EXPIRE_SECONDS),
        last_sent_at=now,
        attempt_count=0,
        max_attempts=5,
        request_ip=request.client.host if request.client else None,
        request_user_agent=request.headers.get("user-agent"),
    )

    try:
        db.add(verification_session)
        await db.commit()
        await db.refresh(verification_session)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create verification session") from exc

    return {
        "data": {
            "verificationSessionId": verification_session.id,
            "ttlSeconds": 180,
            "code": code,
        }
    }


@router.post("/confirm-code")
async def confirm_code(
    payload: ConfirmCodePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    verification_session = await db.get(
        AuthVerificationSession,
        payload.verificationSessionId,
    )
    if not verification_session:
        raise HTTPException(status_code=404, detail="Verification session not found")

    now = datetime.now(timezone.utc)
    verification_session.confirm_ip = request.client.host if request.client else None
    verification_session.confirm_user_agent = request.headers.get("user-agent")

    if verification_session.status != AuthVerificationSessionStatus.PENDING:
        raise HTTPException(status_code=400, detail="Verification session is not active")

    if verification_session.consumed_at is not None:
        raise HTTPException(status_code=400, detail="Verification session already used")

    if ensure_utc(verification_session.expires_at) < now:
        verification_session.status = AuthVerificationSessionStatus.EXPIRED
        verification_session.failed_at = now
        await db.commit()
        await db.refresh(verification_session)
        raise HTTPException(status_code=400, detail="Verification session expired")

    if verification_session.attempt_count >= verification_session.max_attempts:
        verification_session.status = AuthVerificationSessionStatus.FAILED
        verification_session.failed_at = now
        await db.commit()
        await db.refresh(verification_session)
        raise HTTPException(status_code=400, detail="Too many attempts")

    if not verify_code(payload.code, verification_session.code_hash):
        verification_session.attempt_count += 1
        if verification_session.attempt_count >= verification_session.max_attempts:
            verification_session.status = AuthVerificationSessionStatus.FAILED
            verification_session.failed_at = now
        await db.commit()
        await db.refresh(verification_session)
        raise HTTPException(status_code=400, detail="Invalid code")

    verification_session.status = AuthVerificationSessionStatus.VERIFIED
    verification_session.consumed_at = now

    result = await db.execute(
        select(User).where(User.phone == verification_session.phone)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            phone=verification_session.phone,
            verification_status=VerificationStatus.DRAFT,
            last_login_at=now,
        )
        db.add(user)
        await db.flush()
    else:
        user.last_login_at = now

    auth_session = AuthSession(
        id=uuid4(),
        user_id=user.id,
        refresh_token_hash="pending",
        platform=resolve_auth_platform(request),
        device_name=request.headers.get("x-device-name"),
        app_version=request.headers.get("x-app-version"),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        last_used_at=now,
        expires_at=now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    refresh_token = create_refresh_token(user.id, auth_session.id)
    auth_session.refresh_token_hash = hash_refresh_token(refresh_token)
    db.add(auth_session)

    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(user.id, auth_session.id)
    return {
        "data": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "user": {
                "id": user.id,
                "phone": user.phone,
                "verificationStatus": user.verification_status.value,
            },
        }
    }

@router.post("/refresh")
async def refresh(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = extract_bearer_token(request)
    session = await verify_refresh_token(refresh_token, db)

    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    session.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    access_token = create_access_token(session.user_id, session.id)
    return {
        "data": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "user": {
                "id": user.id,
                "phone": user.phone,
                "verificationStatus": user.verification_status.value,
            },
        }
    }

@router.post("/logout")
async def logout(
    request : Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        access_token = extract_bearer_token(request)
        session = await verify_access_token(access_token, db)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to logout") from exc
    try:
        session.last_used_at = datetime.now(timezone.utc)
        session.revoked_at = datetime.now(timezone.utc)
        session.revoke_reason = "logout"
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to logout") from exc
    try:
        await db.commit()
        await db.refresh(session)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to logout") from exc
    return { "data": { "message": "Logged out" } }
