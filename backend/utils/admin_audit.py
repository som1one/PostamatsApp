from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.admin_audit_event import AdminAuditEvent


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def record_admin_audit(
    db: AsyncSession,
    *,
    admin_account_id: UUID,
    action: str,
    request: Request | None = None,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    payload: dict | list | None = None,
) -> None:
    db.add(
        AdminAuditEvent(
            admin_account_id=admin_account_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload_json=payload,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent") if request else None,
        )
    )
