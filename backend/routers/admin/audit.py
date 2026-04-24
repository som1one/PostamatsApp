from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.admin_account import AdminAccount
from backend.models.admin_audit_event import AdminAuditEvent
from backend.routers.admin.auth import get_current_admin

router = APIRouter(prefix="/api/admin/audit", tags=["admin-audit"])


def _serialize_event(ev: AdminAuditEvent, admin: AdminAccount | None) -> dict:
    return {
        "id": str(ev.id),
        "action": ev.action,
        "resourceType": ev.resource_type,
        "resourceId": str(ev.resource_id) if ev.resource_id else None,
        "payload": ev.payload_json,
        "ipAddress": ev.ip_address,
        "createdAt": ev.created_at.isoformat(),
        "admin": (
            {
                "id": str(admin.id),
                "name": admin.name,
                "login": admin.login,
                "role": admin.role.value,
            }
            if admin
            else None
        ),
    }


@router.get("")
async def list_audit_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    action: str | None = Query(None, max_length=128),
    resource_type: str | None = Query(None, alias="resourceType", max_length=64),
):
    await get_current_admin(request, db)

    filters = []
    if action and action.strip():
        filters.append(AdminAuditEvent.action == action.strip())
    if resource_type and resource_type.strip():
        filters.append(AdminAuditEvent.resource_type == resource_type.strip())

    count_stmt = select(func.count()).select_from(AdminAuditEvent)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await db.scalar(count_stmt)) or 0

    stmt = select(AdminAuditEvent)
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.order_by(AdminAuditEvent.created_at.desc()).offset((page - 1) * limit).limit(limit)

    events = (await db.scalars(stmt)).all()

    admin_ids = list({e.admin_account_id for e in events})
    admins = (
        (await db.scalars(select(AdminAccount).where(AdminAccount.id.in_(admin_ids)))).all()
        if admin_ids
        else []
    )
    admin_by_id = {a.id: a for a in admins}

    return {
        "data": {
            "events": [_serialize_event(e, admin_by_id.get(e.admin_account_id)) for e in events],
        },
        "meta": {"page": page, "limit": limit, "total": int(total)},
    }
