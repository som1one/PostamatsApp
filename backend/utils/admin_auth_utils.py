import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from uuid import UUID

import jwt
from fastapi import HTTPException
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.admin_auth_session import AdminAuthSession

PASSWORD_HASH_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_hex, stored_digest = password_hash.split("$", 3)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    try:
        iterations = int(iterations_raw)
    except ValueError:
        return False

    candidate_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return compare_digest(candidate_digest.hex(), stored_digest)


def hash_admin_refresh_token(refresh_token: str) -> str:
    return hashlib.sha512(refresh_token.encode("utf-8")).hexdigest()


def create_admin_access_token(admin_account_id: UUID, session_id: UUID) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(admin_account_id),
            "session_id": str(session_id),
            "token_type": "access",
            "scope": "admin",
            "iat": int(now.timestamp()),
            "exp": int(
                (
                    now
                    + timedelta(seconds=settings.ADMIN_JWT_ACCESS_TOKEN_EXPIRE_SECONDS)
                ).timestamp()
            ),
        },
        settings.ADMIN_JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_admin_refresh_token(admin_account_id: UUID, session_id: UUID) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(admin_account_id),
            "session_id": str(session_id),
            "token_type": "refresh",
            "scope": "admin",
            "iat": int(now.timestamp()),
            "exp": int(
                (
                    now
                    + timedelta(days=settings.ADMIN_JWT_REFRESH_TOKEN_EXPIRE_DAYS)
                ).timestamp()
            ),
        },
        settings.ADMIN_JWT_REFRESH_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def verify_admin_refresh_token(refresh_token: str, db: AsyncSession) -> AdminAuthSession:
    try:
        payload = jwt.decode(
            refresh_token,
            settings.ADMIN_JWT_REFRESH_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Сессия администратора недействительна")

    if payload.get("scope") != "admin" or payload.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="Сессия администратора недействительна")

    session_id = payload.get("session_id")
    subject = payload.get("sub")
    if not session_id or not subject:
        raise HTTPException(status_code=401, detail="Сессия администратора недействительна")

    session = await db.get(AdminAuthSession, UUID(session_id))
    if not session:
        raise HTTPException(status_code=401, detail="Сессия администратора недействительна")

    now = datetime.now(timezone.utc)
    if session.revoked_at is not None or _normalize_datetime(session.expires_at) <= now:
        raise HTTPException(status_code=401, detail="Сессия администратора истекла")

    if str(session.admin_account_id) != str(subject):
        raise HTTPException(status_code=401, detail="Сессия администратора недействительна")

    if hash_admin_refresh_token(refresh_token) != session.refresh_token_hash:
        raise HTTPException(status_code=401, detail="Сессия администратора недействительна")

    return session


async def verify_admin_access_token(access_token: str, db: AsyncSession) -> AdminAuthSession:
    try:
        payload = jwt.decode(
            access_token,
            settings.ADMIN_JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Требуется повторный вход")

    if payload.get("scope") != "admin" or payload.get("token_type") != "access":
        raise HTTPException(status_code=401, detail="Требуется повторный вход")

    session_id = payload.get("session_id")
    subject = payload.get("sub")
    if not session_id or not subject:
        raise HTTPException(status_code=401, detail="Требуется повторный вход")

    session = await db.get(AdminAuthSession, UUID(session_id))
    if not session:
        raise HTTPException(status_code=401, detail="Требуется повторный вход")

    now = datetime.now(timezone.utc)
    if session.revoked_at is not None or _normalize_datetime(session.expires_at) <= now:
        raise HTTPException(status_code=401, detail="Требуется повторный вход")

    if str(session.admin_account_id) != str(subject):
        raise HTTPException(status_code=401, detail="Требуется повторный вход")

    return session
