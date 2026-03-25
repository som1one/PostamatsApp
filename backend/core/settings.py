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