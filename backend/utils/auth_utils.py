import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from uuid import UUID

import jwt
from fastapi import HTTPException, Request
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.auth_session import AuthSession
from backend.models.enums import VerificationStatus
from backend.models.user import User

def generate_code():
    return f"{secrets.randbelow(10000):04d}"


def hash_code(code: str):
    return hashlib.sha512(code.encode()).hexdigest()


def verify_code(code: str, hashed_code: str):
    return compare_digest(hashlib.sha512(code.encode()).hexdigest(), hashed_code)


def hash_refresh_token(refresh_token: str):
    return hashlib.sha512(refresh_token.encode()).hexdigest()


def blocked_account_message(user: User) -> str:
    reason = (user.blocked_reason or "").strip()
    if reason:
        if len(reason) > 280:
            reason = reason[:277] + "..."
        return f"Аккаунт заблокирован. {reason}"
    return "Аккаунт заблокирован. Обратитесь в поддержку."


def ensure_user_not_blocked(user: User) -> None:
    if user.is_blocked or user.verification_status == VerificationStatus.BLOCKED:
        raise HTTPException(status_code=403, detail=blocked_account_message(user))


async def get_current_client_user(request: Request, db: AsyncSession) -> User:
    access_token = extract_bearer_token(request)
    session = await verify_access_token(access_token, db)
    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    ensure_user_not_blocked(user)
    return user


def extract_bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")

    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return token




def create_access_token(user_id: UUID, session_id: UUID):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "session_id": str(session_id),
            "token_type": "access",
            "iat": int(now.timestamp()),
            "exp": int(
                (now + timedelta(seconds=settings.JWT_ACCESS_TOKEN_EXPIRE_SECONDS)).timestamp()
            ),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(user_id: UUID, session_id: UUID):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "session_id": str(session_id),
            "token_type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int(
                (now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)).timestamp()
            ),
        },
        settings.JWT_REFRESH_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

async def verify_refresh_token(refresh_token: str, db: AsyncSession):
    try:
        decoded_refresh_token = jwt.decode(
            refresh_token,
            settings.JWT_REFRESH_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token_type = decoded_refresh_token.get("token_type")
    session_id = decoded_refresh_token.get("session_id")
    subject = decoded_refresh_token.get("sub")

    if token_type != "refresh" or not session_id or not subject:
        raise HTTPException(status_code=401, detail="Unauthorized")

    session = await db.get(AuthSession, UUID(decoded_refresh_token["session_id"]))
    if not session:
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = datetime.now(timezone.utc)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)

    if session.revoked_at is not None or expires_at <= now:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if str(session.user_id) != str(subject):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if hash_refresh_token(refresh_token) != session.refresh_token_hash:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return session


async def verify_access_token(access_token: str, db: AsyncSession):
    try:
        decoded_access_token = jwt.decode(
            access_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token_type = decoded_access_token.get("token_type")
    session_id = decoded_access_token.get("session_id")
    subject = decoded_access_token.get("sub")

    if token_type != "access" or not session_id or not subject:
        raise HTTPException(status_code=401, detail="Unauthorized")

    session = await db.get(AuthSession, UUID(decoded_access_token["session_id"]))
    if not session:
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = datetime.now(timezone.utc)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)

    if session.revoked_at is not None or expires_at <= now:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if str(session.user_id) != str(subject):
        raise HTTPException(status_code=401, detail="Unauthorized")


    return session
