"""Админ-эндпоинты для просмотра и удаления идей аренды."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.media_file import MediaFile
from backend.models.rental_idea import RentalIdea
from backend.routers.admin.auth import get_current_admin
from backend.utils.products_utils import public_media_url


router = APIRouter(prefix="/api/admin/ideas", tags=["admin-rental-ideas"])


def _serialize(idea: RentalIdea, media: MediaFile | None) -> dict:
    photo_url: str | None = None
    if media is not None:
        try:
            photo_url = public_media_url(media.file_key)
        except Exception:
            photo_url = None
    return {
        "id": str(idea.id),
        "name": idea.name,
        "email": idea.email,
        "idea": idea.idea,
        "referenceUrl": idea.reference_url,
        "photoUrl": photo_url,
        "createdAt": idea.created_at.isoformat(),
    }


@router.get("")
async def list_rental_ideas(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    await get_current_admin(request, db)

    total = (await db.scalar(select(func.count()).select_from(RentalIdea))) or 0

    offset = (page - 1) * limit
    stmt = (
        select(RentalIdea, MediaFile)
        .outerjoin(MediaFile, MediaFile.id == RentalIdea.photo_id)
        .order_by(RentalIdea.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    return {
        "data": {
            "items": [_serialize(idea, media) for idea, media in rows],
            "total": int(total),
            "page": page,
            "limit": limit,
        }
    }


@router.delete("/{idea_id}")
async def delete_rental_idea(
    idea_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)
    record = await db.get(RentalIdea, idea_id)
    if record is None:
        raise HTTPException(status_code=404, detail="IDEA_NOT_FOUND")
    await db.delete(record)
    await db.commit()
    return {"data": {"deleted": True}}
