from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.settings import settings
from backend.models.admin_account import AdminAccount
from backend.models.admin_auth_session import AdminAuthSession
from backend.schemas.admin_auth_schemas import AdminLoginPayload
from backend.utils.admin_auth_utils import (
    create_admin_access_token,
    create_admin_refresh_token,
    hash_admin_refresh_token,
    verify_admin_access_token,
    verify_admin_refresh_token,
    verify_password,
)
from backend.utils.auth_utils import extract_bearer_token


router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


def serialize_admin(admin: AdminAccount) -> dict[str, str]:
    return {
        "id": str(admin.id),
        "name": admin.name,
        "login": admin.login,
        "role": admin.role.value,
    }


async def get_current_admin(
    request: Request,
    db: AsyncSession,
) -> tuple[AdminAccount, AdminAuthSession]:
    access_token = extract_bearer_token(request)
    session = await verify_admin_access_token(access_token, db)
    admin = await db.get(AdminAccount, session.admin_account_id)
    if not admin:
        raise HTTPException(status_code=401, detail="Администратор не найден")
    return admin, session


@router.post("/login")
async def login(
    request: Request,
    payload: AdminLoginPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    normalized_login = payload.login.strip().lower()
    password = payload.password.strip()
    if not normalized_login or not password:
        raise HTTPException(status_code=422, detail="Логин и пароль обязательны")

    result = await db.execute(
        select(AdminAccount).where(AdminAccount.login == normalized_login)
    )
    admin = result.scalar_one_or_none()

    if not admin or not verify_password(password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    now = datetime.now(timezone.utc)
    session = AdminAuthSession(
        admin_account_id=admin.id,
        refresh_token_hash="pending",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        last_used_at=now,
        expires_at=now + timedelta(days=settings.ADMIN_JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    await db.flush()

    refresh_token = create_admin_refresh_token(admin.id, session.id)
    session.refresh_token_hash = hash_admin_refresh_token(refresh_token)

    await db.commit()

    access_token = create_admin_access_token(admin.id, session.id)
    return {
        "data": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "admin": serialize_admin(admin),
        }
    }


@router.post("/refresh")
async def refresh(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = extract_bearer_token(request)
    session = await verify_admin_refresh_token(refresh_token, db)

    admin = await db.get(AdminAccount, session.admin_account_id)
    if not admin:
        raise HTTPException(status_code=401, detail="Администратор не найден")

    session.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    access_token = create_admin_access_token(admin.id, session.id)
    return {
        "data": {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "admin": serialize_admin(admin),
        }
    }


@router.get("/me")
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    return {"data": {"admin": serialize_admin(admin)}}


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _, session = await get_current_admin(request, db)
    session.revoked_at = datetime.now(timezone.utc)
    session.revoke_reason = "logout"
    session.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return {"data": {"message": "Сессия закрыта"}}
