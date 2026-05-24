"""
Smoke tests for the SMS-based auth flow.

Verifies the end-to-end behavior of /auth/request-code and /auth/confirm-code
with sms.ru integration mocked, including:
- code generation, hashing, and verification;
- attempt counter and lockout after max attempts;
- TTL expiration handling;
- resend rate-limiting;
- dev-login availability gated by settings.DEBUG.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx

from backend.core.database import Base, get_db
from backend.main import app
from backend.models.auth_verification_session import AuthVerificationSession
from backend.models.enums import AuthVerificationSessionStatus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class AuthSmokeTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end SMS auth flow with sms.ru mocked."""

    async def asyncSetUp(self):
        # Fresh in-memory SQLite + sessionmaker per test, so each test has
        # a clean DB and the engine lives on the test's event loop only.
        self.test_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", echo=False
        )
        self.TestSessionLocal = async_sessionmaker(
            bind=self.test_engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )

        async def override_get_db():
            async with self.TestSessionLocal() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db

        async with self.test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Patch Redis init to no-op (no Redis needed for auth smoke tests).
        self.redis_patcher = patch(
            "backend.core.redis.init_redis", new_callable=AsyncMock
        )
        self.redis_patcher.start()

        # Patch sms.ru sender so tests never hit the network.
        self.sms_patcher = patch(
            "backend.routers.auth.send_auth_code",
            new_callable=AsyncMock,
            return_value="sms-id-stub",
        )
        self.mock_send_auth_code = self.sms_patcher.start()

        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.sms_patcher.stop()
        self.redis_patcher.stop()
        async with self.test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await self.test_engine.dispose()
        app.dependency_overrides.pop(get_db, None)

    # ------------------------------------------------------------------
    # 1. request-code: actually sends SMS via the configured provider
    # ------------------------------------------------------------------

    async def test_request_code_sends_sms(self):
        """POST /auth/request-code triggers send_auth_code with the normalized phone."""
        response = await self.client.post(
            "/auth/request-code",
            json={"phone": "+79991234567"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("verificationSessionId", data)
        self.assertIn("ttlSeconds", data)
        self.mock_send_auth_code.assert_awaited_once()
        sent_phone, sent_code = self.mock_send_auth_code.await_args.args
        self.assertEqual(sent_phone, "+79991234567")
        # The code is a 4-digit numeric string.
        self.assertEqual(len(sent_code), 4)
        self.assertTrue(sent_code.isdigit())

    async def test_request_code_missing_phone(self):
        """request-code without a phone returns 422 AUTH_PHONE_REQUIRED."""
        response = await self.client.post("/auth/request-code", json={})
        self.assertEqual(response.status_code, 422)

    async def test_request_code_resend_too_soon(self):
        """A second request-code for the same phone within 30s returns 429 AUTH_RESEND_TOO_SOON."""
        first = await self.client.post(
            "/auth/request-code", json={"phone": "+79990000001"}
        )
        self.assertEqual(first.status_code, 200)

        second = await self.client.post(
            "/auth/request-code", json={"phone": "+79990000001"}
        )
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["detail"], "AUTH_RESEND_TOO_SOON")

    # ------------------------------------------------------------------
    # 2. confirm-code: full validation
    # ------------------------------------------------------------------

    async def test_confirm_code_success(self):
        """confirm-code with the correct code returns access/refresh tokens and creates a user."""
        phone = "+79991110001"
        req = await self.client.post("/auth/request-code", json={"phone": phone})
        session_id = req.json()["data"]["verificationSessionId"]
        code = self.mock_send_auth_code.await_args.args[1]

        response = await self.client.post(
            "/auth/confirm-code",
            json={"verificationSessionId": session_id, "code": code},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("accessToken", data)
        self.assertIn("refreshToken", data)
        self.assertEqual(data["user"]["phone"], phone)

    async def test_confirm_code_wrong_code(self):
        """An incorrect code returns 401 AUTH_CODE_INVALID and increments attempt_count."""
        phone = "+79991110002"
        req = await self.client.post("/auth/request-code", json={"phone": phone})
        session_id = req.json()["data"]["verificationSessionId"]
        real_code = self.mock_send_auth_code.await_args.args[1]
        wrong_code = "0000" if real_code != "0000" else "1111"

        response = await self.client.post(
            "/auth/confirm-code",
            json={"verificationSessionId": session_id, "code": wrong_code},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "AUTH_CODE_INVALID")

        async with self.TestSessionLocal() as session:
            obj = await session.get(AuthVerificationSession, UUID(session_id))
            self.assertEqual(obj.attempt_count, 1)
            self.assertEqual(obj.status, AuthVerificationSessionStatus.PENDING)

    async def test_confirm_code_too_many_attempts(self):
        """After max_attempts wrong tries the session becomes FAILED and further calls return AUTH_TOO_MANY_ATTEMPTS."""
        phone = "+79991110003"
        req = await self.client.post("/auth/request-code", json={"phone": phone})
        session_id = req.json()["data"]["verificationSessionId"]
        real_code = self.mock_send_auth_code.await_args.args[1]
        wrong_code = "0000" if real_code != "0000" else "1111"

        # Burn all 5 attempts.
        for _ in range(5):
            await self.client.post(
                "/auth/confirm-code",
                json={"verificationSessionId": session_id, "code": wrong_code},
            )

        # Session should now be marked FAILED; another attempt — even with the
        # correct code — returns AUTH_TOO_MANY_ATTEMPTS.
        response = await self.client.post(
            "/auth/confirm-code",
            json={"verificationSessionId": session_id, "code": real_code},
        )
        self.assertIn(response.status_code, (409, 429))
        # 429 if attempt_count check fires first, 409 if status==FAILED check fires first.
        self.assertIn(
            response.json()["detail"],
            ("AUTH_TOO_MANY_ATTEMPTS", "AUTH_SESSION_INACTIVE"),
        )

    async def test_confirm_code_expired_session(self):
        """confirm-code on a session past its TTL returns 410 AUTH_SESSION_EXPIRED."""
        phone = "+79991110004"
        req = await self.client.post("/auth/request-code", json={"phone": phone})
        session_id = req.json()["data"]["verificationSessionId"]
        real_code = self.mock_send_auth_code.await_args.args[1]

        # Manually expire the session in the DB.
        async with self.TestSessionLocal() as session:
            obj = await session.get(AuthVerificationSession, UUID(session_id))
            obj.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

        response = await self.client.post(
            "/auth/confirm-code",
            json={"verificationSessionId": session_id, "code": real_code},
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"], "AUTH_SESSION_EXPIRED")

    async def test_confirm_code_already_used_session(self):
        """confirm-code on a session that's already VERIFIED returns 409 AUTH_SESSION_INACTIVE."""
        phone = "+79991110005"
        req = await self.client.post("/auth/request-code", json={"phone": phone})
        session_id = req.json()["data"]["verificationSessionId"]
        real_code = self.mock_send_auth_code.await_args.args[1]

        first = await self.client.post(
            "/auth/confirm-code",
            json={"verificationSessionId": session_id, "code": real_code},
        )
        self.assertEqual(first.status_code, 200)

        second = await self.client.post(
            "/auth/confirm-code",
            json={"verificationSessionId": session_id, "code": real_code},
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"], "AUTH_SESSION_INACTIVE")

    async def test_confirm_code_unknown_session(self):
        """confirm-code on a non-existent session id returns 404 AUTH_SESSION_NOT_FOUND."""
        response = await self.client.post(
            "/auth/confirm-code",
            json={
                "verificationSessionId": "00000000-0000-0000-0000-000000000000",
                "code": "1234",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "AUTH_SESSION_NOT_FOUND")

    # ------------------------------------------------------------------
    # 3. Full flow: phone → SMS → confirm → tokens → refresh → logout
    # ------------------------------------------------------------------

    async def test_full_flow(self):
        """End-to-end: request-code, confirm-code, refresh, logout."""
        phone = "+79995554433"

        req = await self.client.post("/auth/request-code", json={"phone": phone})
        self.assertEqual(req.status_code, 200)
        session_id = req.json()["data"]["verificationSessionId"]
        code = self.mock_send_auth_code.await_args.args[1]

        confirm = await self.client.post(
            "/auth/confirm-code",
            json={"verificationSessionId": session_id, "code": code},
        )
        self.assertEqual(confirm.status_code, 200)
        tokens = confirm.json()["data"]
        access_token = tokens["accessToken"]
        refresh_token = tokens["refreshToken"]

        refresh = await self.client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        self.assertEqual(refresh.status_code, 200)
        self.assertIn("accessToken", refresh.json()["data"])

        logout = await self.client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.assertEqual(logout.status_code, 200)

    # ------------------------------------------------------------------
    # 4. dev-login: gated by settings.DEBUG
    # ------------------------------------------------------------------

    async def test_dev_login_blocked_in_production(self):
        """When DEBUG is false, /auth/dev-login returns 404."""
        with patch("backend.routers.auth.settings.DEBUG", False):
            response = await self.client.post(
                "/auth/dev-login", json={"phone": "+79990001122"}
            )
        self.assertEqual(response.status_code, 404)

    async def test_dev_login_works_in_debug(self):
        """When DEBUG is true, /auth/dev-login issues tokens without SMS."""
        with patch("backend.routers.auth.settings.DEBUG", True):
            response = await self.client.post(
                "/auth/dev-login", json={"phone": "+79990001133"}
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("accessToken", data)
        self.assertIn("refreshToken", data)
        self.assertEqual(data["user"]["phone"], "+79990001133")
        # dev-login must not call the SMS provider.
        self.mock_send_auth_code.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
