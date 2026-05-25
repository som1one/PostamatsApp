"""Публичный эндпоинт для отправки идеи аренды (страница /ideas)."""

import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.enums import MediaFileKind
from backend.models.media_file import MediaFile
from backend.models.rental_idea import RentalIdea


router = APIRouter(prefix="/api/ideas", tags=["public-rental-ideas"])

# Простая, но достаточная для публичной формы проверка email.
# Не валидируем по RFC — это сделает почтовый провайдер при ответе.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class RentalIdeaCreatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=255)
    idea: str = Field(..., min_length=1, max_length=4000)
    referenceUrl: str | None = Field(default=None, max_length=2048)
    photoId: UUID | None = None


@router.post("")
async def create_rental_idea(
    payload: RentalIdeaCreatePayload = Body(...),
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
    idea = payload.idea.strip()
    reference_url = (payload.referenceUrl or "").strip() or None
    if not name or not idea:
        raise HTTPException(status_code=400, detail="INVALID_PAYLOAD")
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="INVALID_EMAIL")
    if reference_url and not (
        reference_url.startswith("http://") or reference_url.startswith("https://")
    ):
        raise HTTPException(status_code=400, detail="INVALID_REFERENCE_URL")

    record = RentalIdea(
        name=name,
        email=email,
        idea=idea,
        reference_url=reference_url,
        photo_id=photo_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return {"data": {"id": str(record.id)}}
