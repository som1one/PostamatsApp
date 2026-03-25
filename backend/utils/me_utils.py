from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import MediaFileKind
from backend.models.media_file import MediaFile
from backend.models.user import User
from backend.models.verification_request import VerificationRequest
from backend.schemas.me_schemas import VerificationFilePayload


# camelCase (API) -> snake_case (User model)
UPDATE_ME_FIELD_MAP = {
    "firstName": "first_name",
    "lastName": "last_name",
    "middleName": "middle_name",
    "birthDate": "birth_date",
    "preferredCityId": "preferred_city_id",
    "email": "email",
}

FILE_KIND_TO_MEDIA: dict[str, MediaFileKind] = {
    "document_front": MediaFileKind.VERIFICATION_FRONT,
    "document_back": MediaFileKind.VERIFICATION_BACK,
    "selfie": MediaFileKind.VERIFICATION_SELFIE,
}


class VerificationFileResolveError(Exception):
    """Invalid or missing media for verification."""


async def resolve_verification_file_ids(
    db: AsyncSession,
    user_id: UUID,
    files: list[VerificationFilePayload],
) -> tuple[UUID | None, UUID | None, UUID | None]:
    if not files:
        raise VerificationFileResolveError("Files are required")

    front_id: UUID | None = None
    back_id: UUID | None = None
    selfie_id: UUID | None = None

    for item in files:
        expected_kind = FILE_KIND_TO_MEDIA.get(item.kind)
        if expected_kind is None:
            raise VerificationFileResolveError(f"Invalid file kind: {item.kind}")

        result = await db.execute(
            select(MediaFile).where(
                MediaFile.file_key == item.fileKey,
                MediaFile.uploaded_by_user_id == user_id,
            )
        )
        media = result.scalar_one_or_none()
        if media is None:
            raise VerificationFileResolveError(f"File not found or not owned: {item.fileKey}")
        if media.kind != expected_kind:
            raise VerificationFileResolveError(f"File kind mismatch: {item.fileKey}")

        if item.kind == "document_front":
            front_id = media.id
        elif item.kind == "document_back":
            back_id = media.id
        elif item.kind == "selfie":
            selfie_id = media.id

    if front_id is None or selfie_id is None:
        raise VerificationFileResolveError("document_front and selfie files are required")

    return front_id, back_id, selfie_id


def serialize_user(user: User) -> dict:
    data = {
        "id": str(user.id),
        "phone": user.phone,
        "email": user.email,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "middleName": user.middle_name,
        "birthDate": user.birth_date.isoformat() if user.birth_date else None,
        "preferredCityId": str(user.preferred_city_id) if user.preferred_city_id else None,
        "verificationStatus": user.verification_status.value,
        "isBlocked": user.is_blocked,
        "blockedReason": user.blocked_reason,
        "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
    }
    return {key: value for key, value in data.items() if value is not None}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def serialize_verification_request(verification_request: VerificationRequest) -> dict:
    data = {
        "id": str(verification_request.id),
        "status": verification_request.status.value,
        "documentType": verification_request.document_type.value,
        "documentNumber": verification_request.document_number,
        "documentIssueDate": verification_request.document_issue_date.isoformat()
        if verification_request.document_issue_date
        else None,
        "documentExpiryDate": verification_request.document_expiry_date.isoformat()
        if verification_request.document_expiry_date
        else None,
        "rejectReason": verification_request.reject_reason,
    }
    return {key: value for key, value in data.items() if value is not None}


def serialize_verification_not_started() -> dict:
    return {"status": "not_started"}
