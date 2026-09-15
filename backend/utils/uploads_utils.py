import os
import re
from datetime import datetime, timezone
from uuid import UUID

from backend.core.settings import settings
from backend.models.enums import MediaFileKind

PRESIGN_KIND_TO_MEDIA: dict[str, MediaFileKind] = {
    "verification_front": MediaFileKind.VERIFICATION_FRONT,
    "verification_back": MediaFileKind.VERIFICATION_BACK,
    "verification_selfie": MediaFileKind.VERIFICATION_SELFIE,
    "product_cover": MediaFileKind.PRODUCT_COVER,
    "product_gallery": MediaFileKind.PRODUCT_GALLERY,
    "incident_attachment": MediaFileKind.INCIDENT_ATTACHMENT,
    "condition_photo_before": MediaFileKind.CONDITION_PHOTO_BEFORE,
    "condition_photo_after": MediaFileKind.CONDITION_PHOTO_AFTER,
    "rental_idea_photo": MediaFileKind.RENTAL_IDEA_PHOTO,
}

# Папка в ключе: как в примере ТЗ (verification/…), не значение enum целиком.
KIND_TO_FOLDER: dict[str, str] = {
    "verification_front": "verification",
    "verification_back": "verification",
    "verification_selfie": "verification",
    "product_cover": "product",
    "product_gallery": "product",
    "incident_attachment": "incident",
    "condition_photo_before": "condition",
    "condition_photo_after": "condition",
    "rental_idea_photo": "rental-ideas",
}

MIME_BY_KIND: dict[MediaFileKind, frozenset[str]] = {
    MediaFileKind.VERIFICATION_FRONT: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.VERIFICATION_BACK: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.VERIFICATION_SELFIE: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.PRODUCT_COVER: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.PRODUCT_GALLERY: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.INCIDENT_ATTACHMENT: frozenset(
        {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    ),
    MediaFileKind.CONDITION_PHOTO_BEFORE: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.CONDITION_PHOTO_AFTER: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaFileKind.RENTAL_IDEA_PHOTO: frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"}),
}

# Расширение ключа берём из проверенного MIME, а не из имени файла: ключ
# отдаёт StaticFiles по расширению, и «cell.svg» с mimeType image/png иначе
# ушёл бы в браузер как image/svg+xml со скриптом на домене API.
EXTENSION_BY_MIME: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}
MIME_BY_EXTENSION: dict[str, str] = {
    **{extension: mime for mime, extension in EXTENSION_BY_MIME.items()},
    ".jpeg": "image/jpeg",
}
# Неизвестный тип отдаётся как application/octet-stream — браузер его не исполнит.
FALLBACK_EXTENSION = ".bin"

# Лимиты в байтах (MVP)
MAX_FILE_SIZE_IMAGE = 10 * 1024 * 1024
MAX_FILE_SIZE_INCIDENT = 20 * 1024 * 1024
PUBLIC_MEDIA_KINDS = frozenset(
    {
        MediaFileKind.PRODUCT_COVER,
        MediaFileKind.PRODUCT_GALLERY,
        MediaFileKind.RENTAL_IDEA_PHOTO,
    }
)


def max_size_for_kind(media_kind: MediaFileKind) -> int:
    if media_kind == MediaFileKind.INCIDENT_ATTACHMENT:
        return MAX_FILE_SIZE_INCIDENT
    return MAX_FILE_SIZE_IMAGE


def is_public_media_kind(media_kind: MediaFileKind) -> bool:
    return media_kind in PUBLIC_MEDIA_KINDS


def bucket_for_media_kind(media_kind: MediaFileKind) -> str:
    if settings.STORAGE_PROVIDER == "filesystem":
        return "filesystem-public" if is_public_media_kind(media_kind) else "filesystem-private"
    if is_public_media_kind(media_kind):
        return settings.S3_PUBLIC_BUCKET
    return settings.S3_PRIVATE_BUCKET


def sanitize_filename(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", base).strip("-._")
    return (safe[:180] if safe else "file") or "file"


def _file_key_extension(api_kind: str, original_suffix: str, mime_type: str | None) -> str:
    if mime_type is not None:
        return EXTENSION_BY_MIME.get(mime_type.strip().lower(), FALLBACK_EXTENSION)
    # Вызов без MIME (presign админки): расширение имени оставляем, только если
    # оно из разрешённых для вида типов. Иначе — .jpg для видов с картинками
    # (растр под ним гарантирует проверка сигнатуры в PUT), остальным — заглушка.
    allowed = MIME_BY_KIND[PRESIGN_KIND_TO_MEDIA[api_kind]]
    suffix_mime = MIME_BY_EXTENSION.get(original_suffix.lower())
    if suffix_mime is not None and suffix_mime in allowed:
        return EXTENSION_BY_MIME[suffix_mime]
    if "image/jpeg" in allowed:
        return EXTENSION_BY_MIME["image/jpeg"]
    return FALLBACK_EXTENSION


def build_file_key(
    api_kind: str,
    file_id: UUID,
    original_name: str,
    mime_type: str | None = None,
) -> str:
    """Ключ файла: папка вида, дата, uuid и имя клиента с расширением по MIME."""
    folder = KIND_TO_FOLDER[api_kind]
    now = datetime.now(timezone.utc)
    stem, suffix = os.path.splitext(sanitize_filename(original_name))
    extension = _file_key_extension(api_kind, suffix, mime_type)
    return f"{folder}/{now:%Y/%m/%d}/{file_id}-{stem or 'file'}{extension}"


# Сигнатуры растровых форматов: первые байты файла, а не заголовок запроса.
def detect_image_mime(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def image_content_allowed(media_kind: MediaFileKind, content: bytes) -> bool:
    """Байты — картинка одного из разрешённых для вида форматов.

    Совпадение с объявленным MIME не требуем: клиент мог пережать PNG в JPEG
    и не поправить тип. Важно другое — под видом картинки не лежит SVG/HTML.
    """
    detected = detect_image_mime(content)
    return detected is not None and detected in MIME_BY_KIND.get(media_kind, frozenset())
