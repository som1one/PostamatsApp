import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_VALUES = {
    **dotenv_values(BASE_DIR / "backend" / ".env"),
    **dotenv_values(BASE_DIR / ".env.local"),
    **os.environ,
}


def _as_bool(raw: str | None, default: bool) -> bool:
    normalized = (raw or "").strip().lower()
    if normalized in ("1", "true", "yes"):
        return True
    if normalized in ("0", "false", "no"):
        return False
    return default


def _split_csv(raw: str | None) -> list[str]:
    return [item.strip().rstrip("/") for item in (raw or "").split(",") if item.strip()]


class Settings:
    def __init__(self):
        self.DEBUG = ENV_VALUES.get("DEBUG", "false") == "true"
        self.DB_URL = ENV_VALUES.get("DB_URL")
        self.ASYNC_DB_URL = ENV_VALUES.get("ASYNC_DB_URL") or self._build_async_db_url(self.DB_URL)
        self.JWT_SECRET_KEY = ENV_VALUES.get("JWT_SECRET_KEY")
        self.JWT_REFRESH_SECRET_KEY = ENV_VALUES.get("JWT_REFRESH_SECRET_KEY", self.JWT_SECRET_KEY)
        self.JWT_ACCESS_TOKEN_EXPIRE_SECONDS = int(
            ENV_VALUES.get("JWT_ACCESS_TOKEN_EXPIRE_SECONDS", "900")
        )
        self.AUTH_CODE_TTL_SECONDS = int(ENV_VALUES.get("AUTH_CODE_TTL_SECONDS", "180"))
        self.JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(
            ENV_VALUES.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "30")
        )
        self.JWT_ALGORITHM = ENV_VALUES.get("JWT_ALGORITHM", "HS256")
        self.ADMIN_JWT_SECRET_KEY = ENV_VALUES.get(
            "ADMIN_JWT_SECRET_KEY",
            self.JWT_SECRET_KEY,
        )
        self.ADMIN_JWT_REFRESH_SECRET_KEY = ENV_VALUES.get(
            "ADMIN_JWT_REFRESH_SECRET_KEY",
            self.JWT_REFRESH_SECRET_KEY,
        )
        self.ADMIN_JWT_ACCESS_TOKEN_EXPIRE_SECONDS = int(
            ENV_VALUES.get(
                "ADMIN_JWT_ACCESS_TOKEN_EXPIRE_SECONDS",
                str(self.JWT_ACCESS_TOKEN_EXPIRE_SECONDS),
            )
        )
        self.ADMIN_JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(
            ENV_VALUES.get(
                "ADMIN_JWT_REFRESH_TOKEN_EXPIRE_DAYS",
                str(self.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
            )
        )
        self.RESERVATION_QUOTE_EXPIRES_SECONDS = int(
            ENV_VALUES.get("RESERVATION_QUOTE_EXPIRES_SECONDS", "300")
        )
        self.REDIS_URL = (ENV_VALUES.get("REDIS_URL") or "redis://127.0.0.1:6379/0").strip()
        self.SMS_RU_API_ID = (ENV_VALUES.get("SMS_RU_API_ID") or "").strip() or None
        self.SMS_RU_FROM = (ENV_VALUES.get("SMS_RU_FROM") or "").strip() or None
        self.SMS_RU_TIMEOUT_SECONDS = float(ENV_VALUES.get("SMS_RU_TIMEOUT_SECONDS", "10"))

        # S3 / MinIO presign for POST /uploads/presign
        self.AWS_ACCESS_KEY_ID = (ENV_VALUES.get("AWS_ACCESS_KEY_ID") or "").strip() or None
        self.AWS_SECRET_ACCESS_KEY = (
            (ENV_VALUES.get("AWS_SECRET_ACCESS_KEY") or "").strip() or None
        )
        self.S3_BUCKET = (ENV_VALUES.get("S3_BUCKET") or "").strip()
        self.S3_PUBLIC_BUCKET = (
            (ENV_VALUES.get("S3_PUBLIC_BUCKET") or "").strip() or self.S3_BUCKET
        )
        self.S3_PRIVATE_BUCKET = (
            (ENV_VALUES.get("S3_PRIVATE_BUCKET") or "").strip() or self.S3_BUCKET
        )
        self.S3_REGION = ENV_VALUES.get("S3_REGION", "eu-central-1")
        self.S3_ENDPOINT_URL = (ENV_VALUES.get("S3_ENDPOINT_URL") or "").strip() or None
        self.S3_FORCE_PATH_STYLE = _as_bool(ENV_VALUES.get("S3_FORCE_PATH_STYLE"), False)
        self.UPLOAD_PRESIGN_EXPIRES = int(ENV_VALUES.get("UPLOAD_PRESIGN_EXPIRES", "900"))
        self.UPLOAD_DEV_STUB = _as_bool(ENV_VALUES.get("UPLOAD_DEV_STUB"), True)
        self.UPLOAD_DEV_STUB_PUT_URL = ENV_VALUES.get(
            "UPLOAD_DEV_STUB_PUT_URL",
            "https://httpbin.org/put",
        )
        self.STORAGE_PROVIDER = (
            "stub" if self.UPLOAD_DEV_STUB else (ENV_VALUES.get("STORAGE_PROVIDER") or "s3")
        )
        self.LOCAL_UPLOAD_ROOT = (
            ENV_VALUES.get("LOCAL_UPLOAD_ROOT")
            or str((BASE_DIR / "assets" / "runtime-uploads").resolve())
        )
        self.UPLOAD_TOKEN_SECRET = (
            (ENV_VALUES.get("UPLOAD_TOKEN_SECRET") or self.JWT_SECRET_KEY or self.ADMIN_JWT_SECRET_KEY or "").strip()
            or None
        )
        self.MEDIA_PUBLIC_BASE_URL = (ENV_VALUES.get("MEDIA_PUBLIC_BASE_URL") or "").rstrip("/")

        # YooKassa
        self.YOOKASSA_SHOP_ID = (ENV_VALUES.get("YOOKASSA_SHOP_ID") or "").strip() or None
        self.YOOKASSA_SECRET_KEY = (ENV_VALUES.get("YOOKASSA_SECRET_KEY") or "").strip() or None
        self.YOOKASSA_RETURN_URL = (ENV_VALUES.get("YOOKASSA_RETURN_URL") or "").strip() or None
        self.WEB_APP_ORIGIN = (ENV_VALUES.get("WEB_APP_ORIGIN") or "").strip().rstrip("/") or None
        self.CORS_ALLOWED_ORIGINS = self._build_cors_allowed_origins()
        self.YOOKASSA_DEV_STUB = _as_bool(
            ENV_VALUES.get("YOOKASSA_DEV_STUB"),
            not (self.YOOKASSA_SHOP_ID and self.YOOKASSA_SECRET_KEY),
        )

        # ESI (postamats)
        self.ESI_DEV_STUB = _as_bool(ENV_VALUES.get("ESI_DEV_STUB"), True)
        self.ESI_BASE_URL = (ENV_VALUES.get("ESI_BASE_URL") or "").rstrip("/") or None
        self.ESI_API_KEY = (ENV_VALUES.get("ESI_API_KEY") or "").strip() or None
        self.ESI_RESERVE_TIMEOUT = float(ENV_VALUES.get("ESI_RESERVE_TIMEOUT", "15"))
        self.ESI_WEBHOOK_SECRET = (ENV_VALUES.get("ESI_WEBHOOK_SECRET") or "").strip() or None
        self.ESI_DISCOVERY_TIMEOUT = float(ENV_VALUES.get("ESI_DISCOVERY_TIMEOUT", "20"))
        self.ESI_SNAPSHOT_TIMEOUT = float(ENV_VALUES.get("ESI_SNAPSHOT_TIMEOUT", "20"))
        self.ESI_RECONCILE_INTERVAL_SECONDS = int(
            ENV_VALUES.get("ESI_RECONCILE_INTERVAL_SECONDS", "60")
        )
        self.RETURN_REQUEST_TIMEOUT_SECONDS = int(
            ENV_VALUES.get("RETURN_REQUEST_TIMEOUT_SECONDS", "1800")
        )

    def storage_config_error_code(self) -> str | None:
        if self.UPLOAD_DEV_STUB:
            return None
        if self.STORAGE_PROVIDER == "filesystem":
            return None
        if self.STORAGE_PROVIDER != "s3":
            return "STORAGE_PROVIDER_UNSUPPORTED"
        if not self.S3_PUBLIC_BUCKET:
            return "STORAGE_PUBLIC_BUCKET_REQUIRED"
        if not self.S3_PRIVATE_BUCKET:
            return "STORAGE_PRIVATE_BUCKET_REQUIRED"
        if not self.MEDIA_PUBLIC_BASE_URL:
            return "MEDIA_PUBLIC_BASE_URL_REQUIRED"
        has_access_key = bool(self.AWS_ACCESS_KEY_ID)
        has_secret_key = bool(self.AWS_SECRET_ACCESS_KEY)
        if has_access_key != has_secret_key:
            return "STORAGE_CREDENTIALS_INCOMPLETE"
        return None

    def _build_cors_allowed_origins(self) -> list[str]:
        configured = _split_csv(ENV_VALUES.get("CORS_ALLOWED_ORIGINS"))
        if configured:
            return configured

        origins: list[str] = []
        if self.WEB_APP_ORIGIN:
            origins.append(self.WEB_APP_ORIGIN)

            parsed = urlsplit(self.WEB_APP_ORIGIN)
            host = parsed.hostname or ""
            if host and host.count(".") >= 1 and not host.startswith("www."):
                origins.append(
                    urlunsplit(
                        (
                            parsed.scheme,
                            f"www.{host}" + (f":{parsed.port}" if parsed.port else ""),
                            "",
                            "",
                            "",
                        )
                    ).rstrip("/")
                )

        if self.DEBUG:
            origins.extend(
                [
                    "http://127.0.0.1:3001",
                    "http://localhost:3001",
                    "http://192.168.1.6:3001",
                    "http://127.0.0.1:3002",
                    "http://localhost:3002",
                    "http://192.168.1.6:3002",
                ]
            )

        unique: list[str] = []
        for origin in origins:
            if origin and origin not in unique:
                unique.append(origin)
        return unique

    @staticmethod
    def _build_async_db_url(db_url: str | None) -> str | None:
        if not db_url:
            return None

        parts = urlsplit(db_url)
        scheme = parts.scheme

        if scheme == "postgresql":
            scheme = "postgresql+asyncpg"
        elif scheme == "postgresql+psycopg2":
            scheme = "postgresql+asyncpg"
        elif scheme == "postgresql+psycopg":
            scheme = "postgresql+asyncpg"

        return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


settings = Settings()
