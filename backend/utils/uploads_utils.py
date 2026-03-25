import re
from datetime import datetime, timezone
from uuid import UUID

from backend.models.enums import MediaFileKind

PRESIGN_KIND_TO_MEDIA: dict[str, MediaFileKind] = {
    "verification_front": MediaFileKind.VERIFICATION_FRONT,
    "verification_back": MediaFileKind.VERIFICATION_BACK,
    "verification_selfie": MediaFileKind.VERIFICATION_SELFIE,
    "incident_attachment": MediaFileKind.INCIDENT_ATTACHMENT,
    "condition_photo_before": MediaFileKind.CONDITION_PHOTO_BEFORE,
    "condition_photo_after": MediaFileKind.CONDITION_PHOTO_AFTER,
}

# Папка в ключе: как в примере ТЗ (verification/…), не значение enum целиком.
KIND_TO_FOLDER: dict[str, str] = {
    "verification_front": "verification",
    "verification_back": "verification",
    "verification_selfie": "verification",
    "incident_attachment": "incident",
    "condition_photo_before": "condition",
    "condition_photo_after": "condition",
}

MIME_BY_KIND: dict[MediaFileKind, frozenset[str]] = {
    MediaFileKind.VERIFICATION_FRONT: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.VERIFICATION_BACK: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.VERIFICATION_SELFIE: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.INCIDENT_ATTACHMENT: frozenset(
        {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    ),
    MediaFileKind.CONDITION_PHOTO_BEFORE: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.CONDITION_PHOTO_AFTER: frozenset({"image/jpeg", "image/png", "image/webp"}),
}

# Лимиты в байтах (MVP)
MAX_FILE_SIZE_IMAGE = 10 * 1024 * 1024
MAX_FILE_SIZE_INCIDENT = 20 * 1024 * 1024


def max_size_for_kind(media_kind: MediaFileKind) -> int:
    if media_kind == MediaFileKind.INCIDENT_ATTACHMENT:
        return MAX_FILE_SIZE_INCIDENT
    return MAX_FILE_SIZE_IMAGE


def sanitize_filename(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", base).strip("-._")
    return (safe[:180] if safe else "file") or "file"


def build_file_key(api_kind: str, file_id: UUID, original_name: str) -> str:
    folder = KIND_TO_FOLDER[api_kind]
    now = datetime.now(timezone.utc)
    safe = sanitize_filename(original_name)
    return f"{folder}/{now:%Y/%m/%d}/{file_id}-{safe}"
