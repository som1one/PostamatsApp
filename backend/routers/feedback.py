"""Публичная форма обратной связи (страница /ideas на сайте и экран в приложении).

Обращение сохраняется в ``feedback_messages`` и сразу уходит админам в
Telegram и MAX. В записи фиксируем, откуда она пришла: клиент передаёт
``source`` (web / mobile), неизвестное значение честно превращается в
``unknown``, а не в «сайт».

Ручка публичная и дёргает мессенджеры, поэтому на ней тот же лимитер, что
и на заявке на франшизу.
"""

import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.enums import FeedbackSource, FeedbackTopic, MediaFileKind
from backend.models.feedback_message import FeedbackMessage
from backend.models.media_file import MediaFile
from backend.utils.feedback_notifications import notify_feedback_created
from backend.utils.public_rate_limit import RateLimiter, client_ip


router = APIRouter(tags=["public-feedback"])

# Простая, но достаточная для публичной формы проверка email.
# Не валидируем по RFC — это сделает почтовый провайдер при ответе.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

_limiter = RateLimiter(
    per_ip=5,
    per_ip_window=10 * 60,
    global_limit=60,
    global_window=60 * 60,
)


class FeedbackCreatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=255)
    # `idea` — имя поля в первой версии формы; уже установленные сборки
    # приложения шлют именно его, поэтому принимаем оба.
    message: str | None = Field(default=None, min_length=1, max_length=4000)
    idea: str | None = Field(default=None, min_length=1, max_length=4000)
    referenceUrl: str | None = Field(default=None, max_length=2048)
    photoId: UUID | None = None
    source: str | None = Field(default=None, max_length=32)


def resolve_source(raw: str | None) -> str:
    """Приводит присланный клиентом источник к известному значению."""

    value = (raw or "").strip().lower()
    try:
        return FeedbackSource(value).value
    except ValueError:
        return FeedbackSource.UNKNOWN.value


@router.post("/api/feedback")
@router.post("/api/ideas")
async def create_feedback(
    request: Request,
    payload: FeedbackCreatePayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    photo_id: UUID | None = None
    if payload.photoId is not None:
        media = await db.get(MediaFile, payload.photoId)
        if media is None:
            raise HTTPException(status_code=400, detail="PHOTO_NOT_FOUND")
        if media.kind != MediaFileKind.RENTAL_IDEA_PHOTO:
            raise HTTPException(status_code=400, detail="INVALID_PHOTO_KIND")
        photo_id = media.id

    name = payload.name.strip()
    email = payload.email.strip().lower()
    message = (payload.message or payload.idea or "").strip()
    reference_url = (payload.referenceUrl or "").strip() or None
    if not name or not message:
        raise HTTPException(status_code=400, detail="INVALID_PAYLOAD")
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="INVALID_EMAIL")
    if reference_url and not (
        reference_url.startswith("http://") or reference_url.startswith("https://")
    ):
        raise HTTPException(status_code=400, detail="INVALID_REFERENCE_URL")

    if not _limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="TOO_MANY_REQUESTS")

    record = FeedbackMessage(
        topic=FeedbackTopic.IDEA.value,
        source=resolve_source(payload.source),
        name=name,
        email=email,
        message=message,
        reference_url=reference_url,
        photo_id=photo_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    notify_feedback_created(record)

    return {"data": {"id": str(record.id)}}
