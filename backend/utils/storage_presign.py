import logging

from backend.core.exceptions import ClientError
from backend.core.settings import settings

logger = logging.getLogger(__name__)


def presign_put_object(*, bucket: str, file_key: str, content_type: str, expires_in: int) -> str:
    """Return a presigned PUT URL for S3-compatible storage."""
    if settings.UPLOAD_DEV_STUB:
        return settings.UPLOAD_DEV_STUB_PUT_URL

    config_error = settings.storage_config_error_code()
    if config_error:
        raise ClientError(config_error)

    try:
        import boto3
        from botocore.client import Config
        from botocore.exceptions import BotoCoreError, ClientError as BotoClientError
    except ImportError as exc:
        logger.exception("boto3 required for S3 presign")
        raise ClientError("STORAGE_PRESIGN_FAILED") from exc

    config_kwargs: dict[str, object] = {"signature_version": "s3v4"}
    if settings.S3_FORCE_PATH_STYLE:
        config_kwargs["s3"] = {"addressing_style": "path"}

    client_kwargs: dict[str, object] = {
        "service_name": "s3",
        "region_name": settings.S3_REGION,
        "config": Config(**config_kwargs),
    }
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    if settings.S3_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL

    try:
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
    except (BotoCoreError, BotoClientError) as exc:
        logger.exception("S3 presign failed for bucket=%s key=%s", bucket, file_key)
        raise ClientError("STORAGE_PRESIGN_FAILED") from exc
