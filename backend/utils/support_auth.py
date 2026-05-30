"""Authorization helpers for the support chat feature.

This module centralizes the operator-role guard used by the operator REST
routers and the WebSocket handshake verifiers used by the chat gateway.

It deliberately reuses the existing auth machinery rather than introducing a
new auth system:

* client identity comes from :func:`backend.utils.auth_utils.verify_access_token`
* operator identity comes from
  :func:`backend.utils.admin_auth_utils.verify_admin_access_token`
* the admin principal is resolved with
  :func:`backend.routers.admin.auth.get_current_admin`

Only admin accounts whose role passes :func:`operator_has_access` (``OPERATOR``
or ``SUPER_ADMIN``) may use operator chat features (Requirements 7.6, 8.2).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.admin_account import AdminAccount
from backend.models.admin_auth_session import AdminAuthSession
from backend.models.enums import AdminRole
from backend.models.user import User
from backend.routers.admin.auth import get_current_admin
from backend.utils.admin_auth_utils import verify_admin_access_token
from backend.utils.auth_utils import ensure_user_not_blocked, verify_access_token

# Roles that are allowed to use the operator side of support chat.
OPERATOR_ROLES: frozenset[AdminRole] = frozenset(
    {AdminRole.OPERATOR, AdminRole.SUPER_ADMIN}
)

# WebSocket close code used when a handshake fails authentication/authorization
# (Requirements 3.3, 8.4, 8.5). Mirrors the value documented in the design.
WS_UNAUTHORIZED_CLOSE_CODE = 4401


def operator_has_access(role: AdminRole) -> bool:
    """Pure predicate: ``True`` iff ``role`` may access operator chat features.

    Access is granted exactly to ``AdminRole.OPERATOR`` and
    ``AdminRole.SUPER_ADMIN`` and denied for every other role
    (Requirements 7.6, 8.2 — Property 7).
    """

    return role in OPERATOR_ROLES


async def get_current_operator(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[AdminAccount, AdminAuthSession]:
    """FastAPI dependency resolving the current operator admin.

    Reuses :func:`get_current_admin` to resolve the admin identity from the
    bearer access token, then enforces the operator-role guard. Admins whose
    role is neither ``OPERATOR`` nor ``SUPER_ADMIN`` are rejected with ``403``
    (Requirement 8.2).
    """

    admin, session = await get_current_admin(request, db)
    if not operator_has_access(admin.role):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для доступа к поддержке",
        )
    return admin, session


async def authenticate_ws_client(token: str | None, db: AsyncSession) -> User | None:
    """Validate a client ``?token=`` WS handshake and return the ``User``.

    Reuses :func:`verify_access_token` so the WebSocket path enforces the same
    rules as the client REST routes. Returns the authenticated ``User`` on
    success, or ``None`` to signal failure so the gateway can close the socket
    with :data:`WS_UNAUTHORIZED_CLOSE_CODE` (Requirements 3.3, 8.4, 8.5).
    """

    if not token:
        return None

    try:
        session = await verify_access_token(token, db)
    except HTTPException:
        return None

    user = await db.get(User, session.user_id)
    if user is None:
        return None

    try:
        ensure_user_not_blocked(user)
    except HTTPException:
        return None

    return user


async def authenticate_ws_operator(
    token: str | None, db: AsyncSession
) -> AdminAccount | None:
    """Validate an operator ``?token=`` WS handshake and return the admin.

    Reuses :func:`verify_admin_access_token` and then enforces
    :func:`operator_has_access`. Returns the authenticated ``AdminAccount`` on
    success, or ``None`` to signal failure (missing/invalid token, unknown
    admin, or insufficient role) so the gateway can close the socket with
    :data:`WS_UNAUTHORIZED_CLOSE_CODE` (Requirements 8.2, 8.4, 8.5).
    """

    if not token:
        return None

    try:
        session = await verify_admin_access_token(token, db)
    except HTTPException:
        return None

    admin = await db.get(AdminAccount, session.admin_account_id)
    if admin is None:
        return None

    if not operator_has_access(admin.role):
        return None

    return admin
