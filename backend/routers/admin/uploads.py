import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.exceptions import ClientError
from backend.core.settings import settings
from backend.models.media_file import MediaFile
from backend.routers.admin.auth import get_current_admin
from backend.schemas.uploads_schemas import PRESIGN_KIND_VALUES, PresignUploadRequest
from backend.utils.local_storage import build_local_upload_token
from backend.utils.storage_presign import presign_put_object
from backend.utils.uploads_utils import (
    MIME_BY_KIND,
    PRESIGN_KIND_TO_MEDIA,
    bucket_for_media_kind,
    build_file_key,
    max_size_for_kind,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/uploads", tags=["admin-uploads"])
ADMIN_PRESIGN_KIND_VALUES = frozenset({"product_cover", "product_gallery"})


@router.post("/presign")
async def presign_admin_upload(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: PresignUploadRequest = Body(...),
):
    admin = await get_current_admin(request, db)

    if payload.kind not in PRESIGN_KIND_VALUES or payload.kind not in ADMIN_PRESIGN_KIND_VALUES:
        raise HTTPException(status_code=400, detail="INVALID_FILE_KIND")

    media_kind = PRESIGN_KIND_TO_MEDIA[payload.kind]
    allowed_mimes = MIME_BY_KIND[media_kind]
    mime = payload.mimeType.strip().lower()
    if mime not in allowed_mimes:
        raise HTTPException(status_code=400, detail="INVALID_MIME_TYPE")

    max_sz = max_size_for_kind(media_kind)
    if payload.fileSize > max_sz:
        raise HTTPException(status_code=400, detail="FILE_TOO_LARGE")

    file_id = uuid4()
    file_key = build_file_key(payload.kind, file_id, payload.fileName)
    now = datetime.now(timezone.utc)
    bucket = (
        "dev-stub"
        if settings.UPLOAD_DEV_STUB
        else bucket_for_media_kind(media_kind) or "dev-stub"
    )

    media = MediaFile(
        id=file_id,
        storage_provider=settings.STORAGE_PROVIDER,
        bucket=bucket,
        file_key=file_key,
        mime_type=mime,
        file_size=payload.fileSize,
        original_name=payload.fileName,
        kind=media_kind,
        uploaded_by_user_id=None,
        uploaded_by_admin_id=admin.id,
        created_at=now,
    )
    db.add(media)

    try:
        await db.flush()
        expires_in = settings.UPLOAD_PRESIGN_EXPIRES
        if settings.STORAGE_PROVIDER == "filesystem":
            upload_url = str(request.url_for("put_media_upload", file_id=str(media.id)))
            upload_token = build_local_upload_token(
                file_id=media.id,
                file_key=file_key,
                mime_type=mime,
                expires_in=expires_in,
            )
            upload_headers = {"Content-Type": mime, "X-Upload-Token": upload_token}
        else:
            upload_url = presign_put_object(
                bucket=bucket,
                file_key=file_key,
                content_type=mime,
                expires_in=expires_in,
            )
            upload_headers = {"Content-Type": mime}
        await db.commit()
        await db.refresh(media)
    except HTTPException:
        await db.rollback()
        raise
    except ClientError as exc:
        await db.rollback()
        logger.exception("admin upload presign failed")
        raise HTTPException(status_code=500, detail=str(exc) or "STORAGE_PRESIGN_FAILED") from None
    except Exception:
        await db.rollback()
        logger.exception("admin presign upload failed")
        raise HTTPException(status_code=500, detail="STORAGE_PRESIGN_FAILED") from None

    return {
        "data": {
            "fileId": str(media.id),
            "fileKey": media.file_key,
            "uploadUrl": upload_url,
            "method": "PUT",
            "headers": upload_headers,
            "expiresIn": settings.UPLOAD_PRESIGN_EXPIRES,
        }
    }
