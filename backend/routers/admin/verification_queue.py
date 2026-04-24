from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.enums import VerificationStatus
from backend.models.user import User
from backend.models.verification_request import VerificationRequest
from backend.routers.admin.auth import get_current_admin
from backend.routers.admin.users import serialize_admin_user_row

router = APIRouter(prefix="/api/admin/verification-queue", tags=["admin-verification"])


@router.get("")
async def verification_queue(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)

    stmt = (
        select(VerificationRequest)
        .where(VerificationRequest.status == VerificationStatus.PENDING_REVIEW)
        .order_by(VerificationRequest.created_at.asc())
    )
    requests = (await db.scalars(stmt)).all()
    if not requests:
        return {"data": {"items": []}}

    user_ids = list({row.user_id for row in requests})
    users = (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
    user_by_id = {u.id: u for u in users}

    items = []
    for vr in requests:
        u = user_by_id.get(vr.user_id)
        if not u:
            continue
        row = serialize_admin_user_row(u, None)
        items.append(
            {
                "requestId": str(vr.id),
                "userId": str(vr.user_id),
                "userName": row["name"],
                "userPhone": row["phone"],
                "userEmail": row["email"],
                "documentType": vr.document_type.value,
                "documentNumber": vr.document_number,
                "createdAt": vr.created_at.isoformat(),
            }
        )

    return {"data": {"items": items}}
