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
    ensure_user_not_blocked,
    extract_bearer_token,
    generate_code,
    hash_code,
    hash_refresh_token,
    verify_code,
    verify_refresh_token,
    verify_access_token,
)
from backend.utils.phone_utils import normalize_phone_for_storage
from backend.utils.sms_ru import SmsRuError, send_auth_code


router = APIRouter(prefix="/auth", tags=["auth"])  # reload trigger

AUTH_PHONE_REQUIRED = "AUTH_PHONE_REQUIRED"
AUTH_PHONE_INVALID = "AUTH_PHONE_INVALID"
AUTH_SMS_SEND_FAILED = "AUTH_SMS_SEND_FAILED"
AUTH_SMS_PROVIDER_ERROR = "AUTH_SMS_PROVIDER_ERROR"
AUTH_SESSION_NOT_FOUND = "AUTH_SESSION_NOT_FOUND"
AUTH_SESSION_INACTIVE = "AUTH_SESSION_INACTIVE"
AUTH_SESSION_EXPIRED = "AUTH_SESSION_EXPIRED"
AUTH_TOO_MANY_ATTEMPTS = "AUTH_TOO_MANY_ATTEMPTS"
AUTH_CODE_INVALID = "AUTH_CODE_INVALID"
AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"
AUTH_ACCOUNT_BLOCKED = "AUTH_ACCOUNT_BLOCKED"
AUTH_SESSION_CREATE_FAILED = "AUTH_SESSION_CREATE_FAILED"
AUTH_CONFIRM_FAILED = "AUTH_CONFIRM_FAILED"
AUTH_REFRESH_FAILED = "AUTH_REFRESH_FAILED"
AUTH_LOGOUT_FAILED = "AUTH_LOGOUT_FAILED"


def auth_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=code)


def normalize_auth_phone(phone: str) -> str:
    try:
        return normalize_phone_for_storage(phone)
    except ValueError as exc:
        raise auth_error(422, AUTH_PHONE_INVALID) from exc


def ensure_auth_user_not_blocked(user: User) -> None:
    try:
        ensure_user_not_blocked(user)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise auth_error(403, AUTH_ACCOUNT_BLOCKED) from exc
        raise


def require_bearer_token(request: Request) -> str:
    try:
        return extract_bearer_token(request)
    except HTTPException as exc:
        raise auth_error(401, AUTH_UNAUTHORIZED) from exc


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
        raise auth_error(422, AUTH_PHONE_REQUIRED)

    normalized_phone = normalize_auth_phone(resolved_phone)

    now = datetime.now(timezone.utc)
    code = generate_code()
    hashed_code = hash_code(code)
    verification_session = AuthVerificationSession(
        phone=normalized_phone,
        code_hash=hashed_code,
        expires_at=now + timedelta(seconds=settings.AUTH_CODE_TTL_SECONDS),
        last_sent_at=now,
        attempt_count=0,
        max_attempts=5,
        request_ip=request.client.host if request.client else None,
        request_user_agent=request.headers.get("user-agent"),
    )

    try:
        db.add(verification_session)
        await db.flush()
        # DEV: SMS sending disabled for local testing
        # await send_auth_code(normalized_phone, code)
        await db.commit()
        await db.refresh(verification_session)
    except SmsRuError as exc:
        verification_session.status = AuthVerificationSessionStatus.FAILED
        verification_session.failed_at = now
        try:
            await db.commit()
        except Exception:
            await db.rollback()
        raise auth_error(exc.status_code, exc.code) from exc
    except Exception as exc:
        await db.rollback()
        raise auth_error(500, AUTH_SESSION_CREATE_FAILED) from exc

    return {
        "data": {
            "verificationSessionId": verification_session.id,
            "ttlSeconds": settings.AUTH_CODE_TTL_SECONDS,
        }
    }


@router.post("/confirm-code")
async def confirm_code(
    payload: ConfirmCodePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # DEV: Accept any code, just look up the session phone and create user
    verification_session = await db.get(
        AuthVerificationSession,
        payload.verificationSessionId,
    )
    if not verification_session:
        raise auth_error(404, AUTH_SESSION_NOT_FOUND)

    now = datetime.now(timezone.utc)

    verification_session.status = AuthVerificationSessionStatus.VERIFIED
    verification_session.consumed_at = now

    session_phone = normalize_auth_phone(verification_session.phone)

    result = await db.execute(select(User).where(User.phone == session_phone))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            phone=session_phone,
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

    try:
        await db.commit()
        await db.refresh(user)
    except Exception as exc:
        await db.rollback()
        raise auth_error(500, AUTH_CONFIRM_FAILED) from exc

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


# DEV: Instant login without SMS/OTP — for local testing only
@router.post("/dev-login")
async def dev_login(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: RequestCodePayload | None = Body(default=None),
):
    resolved_phone = payload.phone if payload is not None else None
    if not resolved_phone:
        raise auth_error(422, AUTH_PHONE_REQUIRED)

    session_phone = normalize_auth_phone(resolved_phone)
    now = datetime.now(timezone.utc)

    result = await db.execute(select(User).where(User.phone == session_phone))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            phone=session_phone,
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

    try:
        await db.commit()
        await db.refresh(user)
    except Exception as exc:
        await db.rollback()
        raise auth_error(500, AUTH_CONFIRM_FAILED) from exc

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
    refresh_token = require_bearer_token(request)
    try:
        session = await verify_refresh_token(refresh_token, db)
    except HTTPException as exc:
        raise auth_error(401, AUTH_UNAUTHORIZED) from exc

    user = await db.get(User, session.user_id)
    if not user:
        raise auth_error(401, AUTH_UNAUTHORIZED)

    ensure_auth_user_not_blocked(user)

    session.last_used_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise auth_error(500, AUTH_REFRESH_FAILED) from exc

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
    access_token = require_bearer_token(request)
    try:
        session = await verify_access_token(access_token, db)
    except HTTPException as exc:
        raise auth_error(401, AUTH_UNAUTHORIZED) from exc
    session.last_used_at = datetime.now(timezone.utc)
    session.revoked_at = datetime.now(timezone.utc)
    session.revoke_reason = "logout"
    try:
        await db.commit()
        await db.refresh(session)
    except Exception as exc:
        await db.rollback()
        raise auth_error(500, AUTH_LOGOUT_FAILED) from exc
    return { "data": { "message": "Logged out" } }
