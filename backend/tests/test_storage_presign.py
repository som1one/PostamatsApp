import unittest
import tempfile
from pathlib import Path
from uuid import uuid4

from backend.core.exceptions import ClientError
from backend.models.enums import MediaFileKind
from backend.utils.storage_presign import presign_put_object
from backend.utils.local_storage import build_local_upload_token, store_local_upload, verify_local_upload_token
from backend.utils.uploads_utils import bucket_for_media_kind


class StoragePresignTests(unittest.TestCase):
    def setUp(self):
        from backend.utils import storage_presign
        from backend.utils import uploads_utils

        self.storage_presign = storage_presign
        self.uploads_utils = uploads_utils
        self.original = {
            "UPLOAD_DEV_STUB": storage_presign.settings.UPLOAD_DEV_STUB,
            "UPLOAD_DEV_STUB_PUT_URL": storage_presign.settings.UPLOAD_DEV_STUB_PUT_URL,
            "STORAGE_PROVIDER": storage_presign.settings.STORAGE_PROVIDER,
            "S3_PUBLIC_BUCKET": storage_presign.settings.S3_PUBLIC_BUCKET,
            "S3_PRIVATE_BUCKET": storage_presign.settings.S3_PRIVATE_BUCKET,
            "MEDIA_PUBLIC_BASE_URL": storage_presign.settings.MEDIA_PUBLIC_BASE_URL,
            "AWS_ACCESS_KEY_ID": storage_presign.settings.AWS_ACCESS_KEY_ID,
            "AWS_SECRET_ACCESS_KEY": storage_presign.settings.AWS_SECRET_ACCESS_KEY,
            "LOCAL_UPLOAD_ROOT": storage_presign.settings.LOCAL_UPLOAD_ROOT,
            "UPLOAD_TOKEN_SECRET": storage_presign.settings.UPLOAD_TOKEN_SECRET,
        }

    def tearDown(self):
        for key, value in self.original.items():
            setattr(self.storage_presign.settings, key, value)
            setattr(self.uploads_utils.settings, key, value)

    def _set_storage(
        self,
        *,
        stub: bool,
        provider: str = "s3",
        public_bucket: str = "",
        private_bucket: str = "",
        public_base_url: str = "",
        access_key: str | None = None,
        secret_key: str | None = None,
    ):
        self.storage_presign.settings.UPLOAD_DEV_STUB = stub
        self.storage_presign.settings.STORAGE_PROVIDER = provider
        self.storage_presign.settings.S3_PUBLIC_BUCKET = public_bucket
        self.storage_presign.settings.S3_PRIVATE_BUCKET = private_bucket
        self.storage_presign.settings.MEDIA_PUBLIC_BASE_URL = public_base_url
        self.storage_presign.settings.AWS_ACCESS_KEY_ID = access_key
        self.storage_presign.settings.AWS_SECRET_ACCESS_KEY = secret_key
        self.storage_presign.settings.LOCAL_UPLOAD_ROOT = str(Path(tempfile.gettempdir()) / "postamats-test-uploads")

        self.uploads_utils.settings.UPLOAD_DEV_STUB = stub
        self.uploads_utils.settings.STORAGE_PROVIDER = provider
        self.uploads_utils.settings.S3_PUBLIC_BUCKET = public_bucket
        self.uploads_utils.settings.S3_PRIVATE_BUCKET = private_bucket
        self.uploads_utils.settings.MEDIA_PUBLIC_BASE_URL = public_base_url
        self.uploads_utils.settings.AWS_ACCESS_KEY_ID = access_key
        self.uploads_utils.settings.AWS_SECRET_ACCESS_KEY = secret_key
        self.uploads_utils.settings.LOCAL_UPLOAD_ROOT = str(Path(tempfile.gettempdir()) / "postamats-test-uploads")
        self.storage_presign.settings.UPLOAD_TOKEN_SECRET = "test-upload-secret"
        self.uploads_utils.settings.UPLOAD_TOKEN_SECRET = "test-upload-secret"

    def test_stub_mode_returns_stub_url(self):
        self.storage_presign.settings.UPLOAD_DEV_STUB = True
        self.storage_presign.settings.UPLOAD_DEV_STUB_PUT_URL = "https://example.test/put"

        result = presign_put_object(
            bucket="dev-stub",
            file_key="verification/demo.jpg",
            content_type="image/jpeg",
            expires_in=900,
        )

        self.assertEqual(result, "https://example.test/put")

    def test_presign_requires_public_bucket(self):
        self._set_storage(stub=False)

        with self.assertRaises(ClientError) as context:
            presign_put_object(
                bucket="",
                file_key="product/demo.jpg",
                content_type="image/jpeg",
                expires_in=900,
            )

        self.assertEqual(str(context.exception), "STORAGE_PUBLIC_BUCKET_REQUIRED")

    def test_presign_requires_complete_credentials(self):
        self._set_storage(
            stub=False,
            public_bucket="naprokatberu-public",
            private_bucket="naprokatberu-private",
            public_base_url="https://cdn.naprokatberu.ru",
            access_key="only-key",
            secret_key=None,
        )

        with self.assertRaises(ClientError) as context:
            presign_put_object(
                bucket="naprokatberu-private",
                file_key="verification/demo.jpg",
                content_type="image/jpeg",
                expires_in=900,
            )

        self.assertEqual(str(context.exception), "STORAGE_CREDENTIALS_INCOMPLETE")

    def test_bucket_selection_separates_public_and_private_media(self):
        self._set_storage(
            stub=False,
            public_bucket="naprokatberu-public",
            private_bucket="naprokatberu-private",
            public_base_url="https://cdn.naprokatberu.ru",
        )

        self.assertEqual(
            bucket_for_media_kind(MediaFileKind.PRODUCT_COVER),
            "naprokatberu-public",
        )
        self.assertEqual(
            bucket_for_media_kind(MediaFileKind.VERIFICATION_FRONT),
            "naprokatberu-private",
        )

    def test_filesystem_upload_token_roundtrip_and_local_store(self):
        self._set_storage(
            stub=False,
            provider="filesystem",
            public_base_url="",
        )

        file_id = uuid4()
        token = build_local_upload_token(
            file_id=file_id,
            file_key="verification/2026/05/17/demo.jpg",
            mime_type="image/jpeg",
            expires_in=900,
        )
        payload = verify_local_upload_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["fileId"], str(file_id))
        self.assertEqual(payload["mimeType"], "image/jpeg")

        written = store_local_upload(
            "verification/2026/05/17/demo.jpg",
            b"hello-world",
        )
        self.assertTrue(written.exists())
        self.assertEqual(written.read_bytes(), b"hello-world")
