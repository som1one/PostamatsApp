"""Админ-эндпоинты раздела «Обратная связь»: список и удаление обращений."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.utils.admin_scope import require_full_access_admin
from backend.models.feedback_message import FeedbackMessage
from backend.models.media_file import MediaFile
from backend.routers.admin.auth import get_current_admin
from backend.utils.feedback_notifications import source_label, topic_label
from backend.utils.products_utils import public_media_url


router = APIRouter(
    prefix="/api/admin/feedback",
    tags=["admin-feedback"],
    # Обращения приходят с публичных форм по всей стране — не для франшизы.
    dependencies=[Depends(require_full_access_admin)],
)


def _serialize(record: FeedbackMessage, media: MediaFile | None) -> dict:
    photo_url: str | None = None
    if media is not None:
        try:
            photo_url = public_media_url(media.file_key)
        except Exception:
            photo_url = None
    return {
        "id": str(record.id),
        "topic": record.topic,
        "topicLabel": topic_label(record.topic),
        "source": record.source,
        "sourceLabel": source_label(record.source),
        "name": record.name,
        "email": record.email,
        "phone": record.phone,
        "city": record.city,
        "message": record.message,
        "referenceUrl": record.reference_url,
        "photoUrl": photo_url,
        "createdAt": record.created_at.isoformat(),
    }


@router.get("")
async def list_feedback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    topic: str | None = Query(None, max_length=32),
):
    await get_current_admin(request, db)

    filters = []
    if topic:
        filters.append(FeedbackMessage.topic == topic)

    total_stmt = select(func.count()).select_from(FeedbackMessage)
    for condition in filters:
        total_stmt = total_stmt.where(condition)
    total = (await db.scalar(total_stmt)) or 0

    offset = (page - 1) * limit
    stmt = (
        select(FeedbackMessage, MediaFile)
        .outerjoin(MediaFile, MediaFile.id == FeedbackMessage.photo_id)
        .order_by(FeedbackMessage.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    for condition in filters:
        stmt = stmt.where(condition)
    rows = (await db.execute(stmt)).all()

    return {
        "data": {
            "items": [_serialize(record, media) for record, media in rows],
            "total": int(total),
            "page": page,
            "limit": limit,
        }
    }


@router.delete("/{feedback_id}")
async def delete_feedback(
    feedback_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)
    record = await db.get(FeedbackMessage, feedback_id)
    if record is None:
        raise HTTPException(status_code=404, detail="FEEDBACK_NOT_FOUND")
    await db.delete(record)
    await db.commit()
    return {"data": {"deleted": True}}
