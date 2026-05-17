import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from backend.core.exceptions import ClientError
from backend.core.settings import settings


def _upload_secret() -> str:
    secret = settings.UPLOAD_TOKEN_SECRET
    if not secret:
        raise ClientError("UPLOAD_TOKEN_SECRET_REQUIRED")
    return secret


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("ascii"))


def build_local_upload_token(
    *,
    file_id: UUID,
    file_key: str,
    mime_type: str,
    expires_in: int,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "fileId": str(file_id),
        "fileKey": file_key,
        "mimeType": mime_type,
        "exp": int(now.timestamp()) + max(1, int(expires_in)),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_upload_secret().encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return f"{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"


def verify_local_upload_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    payload_raw, signature_raw = token.split(".", 1)
    try:
        payload_bytes = _b64url_decode(payload_raw)
        signature = _b64url_decode(signature_raw)
    except Exception:
        return None

    expected = hmac.new(_upload_secret().encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, signature):
        return None

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None

    try:
        expires_at = int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return None
    if expires_at <= int(datetime.now(timezone.utc).timestamp()):
        return None

    return payload if isinstance(payload, dict) else None


def local_upload_path(file_key: str) -> Path:
    root = Path(settings.LOCAL_UPLOAD_ROOT).resolve()
    target = (root / file_key.lstrip("/")).resolve()
    if target != root and root not in target.parents:
        raise ClientError("LOCAL_UPLOAD_PATH_INVALID")
    return target


def store_local_upload(file_key: str, content: bytes) -> Path:
    target = local_upload_path(file_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target
