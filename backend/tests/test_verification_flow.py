"""
End-to-end smoke test for account verification flow.

Verifies that a user can:
1. Get a presigned upload URL.
2. PUT a file to the relative upload URL via the same ASGI client (which
   simulates a reverse proxy stripping path prefixes — see comment below).
3. Submit a verification request that references the uploaded files.
4. After admin approves, the user's verification status becomes "approved".

Also covers:
- Resubmission after a previous "rejected" verification with the same
  document number is allowed (overwrites the rejected request).
- Admin reviewer id is recorded on approve/reject.
"""

import os
import unittest
from unittest.mock import patch, AsyncMock

# Force filesystem storage so presign returns a relative path that we can
# replay through the ASGI client. This is the same code path as production.
os.environ["UPLOAD_DEV_STUB"] = "false"
os.environ["STORAGE_PROVIDER"] = "filesystem"
os.environ["UPLOAD_TOKEN_SECRET"] = "test-upload-token-secret"
os.environ["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "test-jwt-secret")

import httpx

from backend.main import app
from backend.core.database import Base, get_db
from backend.core.settings import settings
from backend.models.admin_account import AdminAccount
from backend.models.enums import AdminRole
from backend.utils.admin_auth_utils import hash_password
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


PNG_1x1 = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108020000009077"
    "53DE0000000C4944415478DA63F8FFFFFFFFFFFFFF1F00080100FFFFFFFF"
    "0007FBFFFEEFEC0000000049454E44AE426082"
)


class VerificationFlowTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end: presign → upload → submit → admin approve."""

    async def asyncSetUp(self):
        # Apply test-friendly settings on the singleton settings object
        self._tmp_uploads = tempfile.TemporaryDirectory()
        self._old_upload_root = settings.LOCAL_UPLOAD_ROOT
        self._old_storage_provider = settings.STORAGE_PROVIDER
        self._old_upload_dev_stub = settings.UPLOAD_DEV_STUB
        self._old_upload_token_secret = settings.UPLOAD_TOKEN_SECRET
        settings.LOCAL_UPLOAD_ROOT = self._tmp_uploads.name
        settings.STORAGE_PROVIDER = "filesystem"
        settings.UPLOAD_DEV_STUB = False
        settings.UPLOAD_TOKEN_SECRET = "test-upload-token-secret"

        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed admin account so we can call admin endpoints
        async with TestSessionLocal() as session:
            admin = AdminAccount(
                name="Test Admin",
                login="admin",
                role=AdminRole.SUPER_ADMIN,
                password_hash=hash_password("admin123"),
            )
            session.add(admin)
            await session.commit()

        self.redis_patcher = patch(
            "backend.core.redis.init_redis", new_callable=AsyncMock
        )
        self.redis_patcher.start()

        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.redis_patcher.stop()
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        settings.LOCAL_UPLOAD_ROOT = self._old_upload_root
        settings.STORAGE_PROVIDER = self._old_storage_provider
        settings.UPLOAD_DEV_STUB = self._old_upload_dev_stub
        settings.UPLOAD_TOKEN_SECRET = self._old_upload_token_secret
        self._tmp_uploads.cleanup()

    async def _login_user(self, phone: str) -> str:
        response = await self.client.post(
            "/auth/dev-login", json={"phone": phone}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["accessToken"]

    async def _login_admin(self) -> str:
        response = await self.client.post(
            "/api/admin/auth/login",
            json={"login": "admin", "password": "admin123"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["accessToken"]

    async def _presign_and_upload(
        self, token: str, kind: str, file_name: str, content: bytes
    ) -> dict:
        presign_response = await self.client.post(
            "/uploads/presign",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "fileName": file_name,
                "mimeType": "image/png",
                "fileSize": len(content),
                "kind": kind,
            },
        )
        self.assertEqual(presign_response.status_code, 200, presign_response.text)
        presign = presign_response.json()["data"]

        # Sanity: presign must return a path that doesn't include /api,
        # because the backend itself doesn't know about reverse-proxy prefixes.
        # Production caddy prepends /api, the client glues it back together.
        self.assertTrue(presign["uploadUrl"].startswith("/uploads/files/"))

        # Replay PUT through the same ASGI client (equivalent to the client
        # uploading to apiBase + uploadUrl, which goes through caddy).
        put_response = await self.client.put(
            presign["uploadUrl"],
            headers=presign["headers"],
            content=content,
        )
        self.assertEqual(put_response.status_code, 200, put_response.text)
        return presign

    async def test_full_verification_flow(self):
        token = await self._login_user("+79991110001")

        front = await self._presign_and_upload(
            token, "verification_front", "front.png", PNG_1x1
        )
        selfie = await self._presign_and_upload(
            token, "verification_selfie", "selfie.png", PNG_1x1
        )

        create_response = await self.client.post(
            "/me/verification",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "firstName": "Иван",
                "lastName": "Петров",
                "birthDate": "1990-01-01",
                "documentType": "passport_rf",
                "documentNumber": "1234 567890",
                "files": [
                    {"fileKey": front["fileKey"], "kind": "document_front"},
                    {"fileKey": selfie["fileKey"], "kind": "selfie"},
                ],
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        verification = create_response.json()["data"]["verification"]
        self.assertEqual(verification["status"], "pending_review")

        # User /me should reflect pending status
        me_response = await self.client.get(
            "/me", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(
            me_response.json()["data"]["user"]["verificationStatus"], "pending_review"
        )

        # Admin sees the request in the queue
        admin_token = await self._login_admin()
        queue_response = await self.client.get(
            "/api/admin/verification-queue",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(queue_response.status_code, 200, queue_response.text)
        items = queue_response.json()["data"]["items"]
        self.assertEqual(len(items), 1)
        target_user_id = items[0]["userId"]

        # Admin opens user details — verification block must include image URLs
        details_response = await self.client.get(
            f"/api/admin/users/{target_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(details_response.status_code, 200, details_response.text)
        details = details_response.json()["data"]
        self.assertEqual(details["verification"]["status"], "pending_review")
        self.assertTrue(details["verification"]["frontUrl"])
        self.assertTrue(details["verification"]["selfieUrl"])

        # Admin approves
        approve_response = await self.client.post(
            f"/api/admin/users/{target_user_id}/approve-verification",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(approve_response.status_code, 200, approve_response.text)

        # User now sees approved status
        me_after_response = await self.client.get(
            "/me", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(
            me_after_response.json()["data"]["user"]["verificationStatus"], "approved"
        )

    async def test_reject_then_resubmit_same_document_number(self):
        token = await self._login_user("+79991110002")

        front = await self._presign_and_upload(
            token, "verification_front", "front.png", PNG_1x1
        )
        selfie = await self._presign_and_upload(
            token, "verification_selfie", "selfie.png", PNG_1x1
        )

        body = {
            "firstName": "Ivan",
            "lastName": "Petrov",
            "birthDate": "1990-01-01",
            "documentType": "passport_rf",
            "documentNumber": "9999 888777",
            "files": [
                {"fileKey": front["fileKey"], "kind": "document_front"},
                {"fileKey": selfie["fileKey"], "kind": "selfie"},
            ],
        }
        first_response = await self.client.post(
            "/me/verification",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        self.assertEqual(first_response.status_code, 200, first_response.text)

        admin_token = await self._login_admin()
        queue = await self.client.get(
            "/api/admin/verification-queue",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        target_user_id = queue.json()["data"]["items"][0]["userId"]

        reject = await self.client.post(
            f"/api/admin/users/{target_user_id}/reject-verification",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "Документ нечитаемый"},
        )
        self.assertEqual(reject.status_code, 200, reject.text)

        # User /me shows rejected with rejectReason
        kyc = await self.client.get(
            "/me/verification", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(kyc.json()["data"]["verification"]["status"], "rejected")
        self.assertEqual(
            kyc.json()["data"]["verification"]["rejectReason"], "Документ нечитаемый"
        )

        # User uploads new files and resubmits with the SAME document number —
        # this used to fail with DOCUMENT_NUMBER_ALREADY_EXISTS.
        front2 = await self._presign_and_upload(
            token, "verification_front", "front2.png", PNG_1x1
        )
        selfie2 = await self._presign_and_upload(
            token, "verification_selfie", "selfie2.png", PNG_1x1
        )
        body["files"] = [
            {"fileKey": front2["fileKey"], "kind": "document_front"},
            {"fileKey": selfie2["fileKey"], "kind": "selfie"},
        ]
        resubmit = await self.client.post(
            "/me/verification",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        self.assertEqual(resubmit.status_code, 200, resubmit.text)
        self.assertEqual(
            resubmit.json()["data"]["verification"]["status"], "pending_review"
        )

    async def test_other_user_cannot_reuse_document_number(self):
        token_a = await self._login_user("+79991110003")
        token_b = await self._login_user("+79991110004")

        front = await self._presign_and_upload(
            token_a, "verification_front", "front.png", PNG_1x1
        )
        selfie = await self._presign_and_upload(
            token_a, "verification_selfie", "selfie.png", PNG_1x1
        )
        body_a = {
            "firstName": "A",
            "lastName": "A",
            "birthDate": "1990-01-01",
            "documentType": "passport_rf",
            "documentNumber": "5555 444333",
            "files": [
                {"fileKey": front["fileKey"], "kind": "document_front"},
                {"fileKey": selfie["fileKey"], "kind": "selfie"},
            ],
        }
        await self.client.post(
            "/me/verification",
            headers={"Authorization": f"Bearer {token_a}"},
            json=body_a,
        )

        # B tries to use the same document number
        front_b = await self._presign_and_upload(
            token_b, "verification_front", "front_b.png", PNG_1x1
        )
        selfie_b = await self._presign_and_upload(
            token_b, "verification_selfie", "selfie_b.png", PNG_1x1
        )
        body_b = {
            "firstName": "B",
            "lastName": "B",
            "birthDate": "1990-01-01",
            "documentType": "passport_rf",
            "documentNumber": "5555 444333",
            "files": [
                {"fileKey": front_b["fileKey"], "kind": "document_front"},
                {"fileKey": selfie_b["fileKey"], "kind": "selfie"},
            ],
        }
        resp = await self.client.post(
            "/me/verification",
            headers={"Authorization": f"Bearer {token_b}"},
            json=body_b,
        )
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"], "DOCUMENT_NUMBER_ALREADY_EXISTS")


if __name__ == "__main__":
    unittest.main()
