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

        # S3 / MinIO presign для POST /uploads/presign
        self.AWS_ACCESS_KEY_ID = ENV_VALUES.get("AWS_ACCESS_KEY_ID")
        self.AWS_SECRET_ACCESS_KEY = ENV_VALUES.get("AWS_SECRET_ACCESS_KEY")
        self.S3_BUCKET = ENV_VALUES.get("S3_BUCKET", "")
        self.S3_REGION = ENV_VALUES.get("S3_REGION", "eu-central-1")
        self.S3_ENDPOINT_URL = ENV_VALUES.get("S3_ENDPOINT_URL") or None
        self.UPLOAD_PRESIGN_EXPIRES = int(ENV_VALUES.get("UPLOAD_PRESIGN_EXPIRES", "900"))
        _stub_raw = (ENV_VALUES.get("UPLOAD_DEV_STUB") or "").strip().lower()
        if _stub_raw in ("1", "true", "yes"):
            self.UPLOAD_DEV_STUB = True
        elif _stub_raw in ("0", "false", "no"):
            self.UPLOAD_DEV_STUB = False
        else:
            # По умолчанию заглушка; в проде задайте UPLOAD_DEV_STUB=0 и S3/MinIO или IAM.
            self.UPLOAD_DEV_STUB = True
        self.UPLOAD_DEV_STUB_PUT_URL = ENV_VALUES.get(
            "UPLOAD_DEV_STUB_PUT_URL",
            "https://httpbin.org/put",
        )
        self.STORAGE_PROVIDER = (
            "stub" if self.UPLOAD_DEV_STUB else (ENV_VALUES.get("STORAGE_PROVIDER") or "s3")
        )
        self.MEDIA_PUBLIC_BASE_URL = (ENV_VALUES.get("MEDIA_PUBLIC_BASE_URL") or "").rstrip("/")

        # YooKassa
        self.YOOKASSA_SHOP_ID = (ENV_VALUES.get("YOOKASSA_SHOP_ID") or "").strip() or None
        self.YOOKASSA_SECRET_KEY = (ENV_VALUES.get("YOOKASSA_SECRET_KEY") or "").strip() or None
        self.YOOKASSA_RETURN_URL = (ENV_VALUES.get("YOOKASSA_RETURN_URL") or "").strip() or None
        _yk_stub = (ENV_VALUES.get("YOOKASSA_DEV_STUB") or "").strip().lower()
        if _yk_stub in ("1", "true", "yes"):
            self.YOOKASSA_DEV_STUB = True
        elif _yk_stub in ("0", "false", "no"):
            self.YOOKASSA_DEV_STUB = False
        else:
            self.YOOKASSA_DEV_STUB = not (self.YOOKASSA_SHOP_ID and self.YOOKASSA_SECRET_KEY)

        # ESI (постаматы)
        _esi_stub = (ENV_VALUES.get("ESI_DEV_STUB") or "").strip().lower()
        if _esi_stub in ("1", "true", "yes"):
            self.ESI_DEV_STUB = True
        elif _esi_stub in ("0", "false", "no"):
            self.ESI_DEV_STUB = False
        else:
            self.ESI_DEV_STUB = True
        self.ESI_BASE_URL = (ENV_VALUES.get("ESI_BASE_URL") or "").rstrip("/") or None
        self.ESI_API_KEY = (ENV_VALUES.get("ESI_API_KEY") or "").strip() or None
        self.ESI_RESERVE_TIMEOUT = float(ENV_VALUES.get("ESI_RESERVE_TIMEOUT", "15"))
        self.ESI_WEBHOOK_SECRET = (ENV_VALUES.get("ESI_WEBHOOK_SECRET") or "").strip() or None
        self.ESI_DISCOVERY_TIMEOUT = float(ENV_VALUES.get("ESI_DISCOVERY_TIMEOUT", "20"))

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
