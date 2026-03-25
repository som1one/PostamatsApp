import logging

from backend.core.settings import settings

logger = logging.getLogger(__name__)


def presign_put_object(*, bucket: str, file_key: str, content_type: str, expires_in: int) -> str:
    """Возвращает presigned PUT URL для S3-совместимого хранилища."""
    if settings.UPLOAD_DEV_STUB:
        return settings.UPLOAD_DEV_STUB_PUT_URL

    try:
        import boto3
        from botocore.client import Config
    except ImportError as exc:
        logger.exception("boto3 required for S3 presign")
        raise RuntimeError("STORAGE_PRESIGN_FAILED") from exc

    client_kwargs: dict = {
        "service_name": "s3",
        "region_name": settings.S3_REGION,
        "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
        "config": Config(signature_version="s3v4"),
    }
    if settings.S3_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL

    client = boto3.client(**client_kwargs)
    return client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": bucket,
            "Key": file_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )
