import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.core.exceptions import ClientError
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.settings import settings
from backend.models.admin_user import AdminUser
from backend.models.media_file import MediaFile
from backend.schemas.uploads_schemas import PRESIGN_KIND_VALUES, PresignUploadRequest
from backend.utils.auth_utils import get_current_client_user
from backend.utils.storage_presign import presign_put_object
from backend.utils.uploads_utils import (
    PRESIGN_KIND_TO_MEDIA,
    max_size_for_kind,
    build_file_key,
    MIME_BY_KIND,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/uploads", tags=["uploads"])
CLIENT_PRESIGN_KIND_VALUES = PRESIGN_KIND_VALUES.difference({"product_cover", "product_gallery"})


@router.post("/presign")
async def presign_upload(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: PresignUploadRequest = Body(...),
):
    user = await get_current_client_user(request, db)

    if payload.kind not in CLIENT_PRESIGN_KIND_VALUES:
        raise HTTPException(status_code=400, detail="INVALID_FILE_KIND")

    media_kind = PRESIGN_KIND_TO_MEDIA[payload.kind]
    allowed_mimes = MIME_BY_KIND[media_kind]
    mime = payload.mimeType.strip().lower()
    if mime not in allowed_mimes:
        raise HTTPException(status_code=400, detail="INVALID_MIME_TYPE")

    max_sz = max_size_for_kind(media_kind)
    if payload.fileSize > max_sz:
        raise HTTPException(status_code=400, detail="FILE_TOO_LARGE")

    result = await db.execute(select(AdminUser).where(AdminUser.user_id == user.id))
    admin = result.scalar_one_or_none()

    file_id = uuid4()
    file_key = build_file_key(payload.kind, file_id, payload.fileName)
    now = datetime.now(timezone.utc)
    bucket = settings.S3_BUCKET or "dev-stub"

    media = MediaFile(
        id=file_id,
        storage_provider=settings.STORAGE_PROVIDER,
        bucket=bucket,
        file_key=file_key,
        mime_type=mime,
        file_size=payload.fileSize,
        original_name=payload.fileName,
        kind=media_kind,
        uploaded_by_user_id=user.id if admin is None else None,
        uploaded_by_admin_id=admin.id if admin is not None else None,
        created_at=now,
    )
    db.add(media)

    try:
        await db.flush()
        expires_in = settings.UPLOAD_PRESIGN_EXPIRES
        if not settings.UPLOAD_DEV_STUB and not settings.S3_BUCKET:
            raise HTTPException(status_code=500, detail="STORAGE_PRESIGN_FAILED")
        upload_url = presign_put_object(
            bucket=bucket,
            file_key=file_key,
            content_type=mime,
            expires_in=expires_in,
        )
        await db.commit()
        await db.refresh(media)
    except HTTPException:
        await db.rollback()
        raise
    except ClientError:
        await db.rollback()
        logger.exception("S3 presign failed")
        raise HTTPException(status_code=500, detail="STORAGE_PRESIGN_FAILED") from None
    except Exception:
        await db.rollback()
        logger.exception("presign upload failed")
        raise HTTPException(status_code=500, detail="STORAGE_PRESIGN_FAILED") from None

    return {
        "data": {
            "fileId": str(media.id),
            "fileKey": media.file_key,
            "uploadUrl": upload_url,
            "method": "PUT",
            "headers": {"Content-Type": mime},
            "expiresIn": settings.UPLOAD_PRESIGN_EXPIRES,
        }
    }
