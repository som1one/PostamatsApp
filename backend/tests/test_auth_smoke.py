"""
Smoke tests for auth flow with SMS verification disabled.

Verifies that a user can enter a phone number and immediately
get into the app without OTP errors.
"""

import unittest
from unittest.mock import patch, AsyncMock

import httpx

from backend.main import app
from backend.core.database import Base, get_db

# Use SQLite async in-memory for isolation
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


class AuthSmokeTests(unittest.IsolatedAsyncioTestCase):
    """Smoke tests: login by phone number without SMS verification."""

    async def asyncSetUp(self):
        # Create all tables in the in-memory SQLite DB
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Patch Redis init to no-op (no Redis needed for auth smoke tests)
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

    # ------------------------------------------------------------------
    # 1. dev-login: instant login by phone number
    # ------------------------------------------------------------------

    async def test_dev_login_success(self):
        """POST /auth/dev-login with a valid phone returns tokens immediately."""
        response = await self.client.post(
            "/auth/dev-login",
            json={"phone": "+79991234567"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("accessToken", data)
        self.assertIn("refreshToken", data)
        self.assertIn("user", data)
        self.assertEqual(data["user"]["phone"], "+79991234567")

    async def test_dev_login_creates_user(self):
        """dev-login creates a new user if one doesn't exist."""
        response = await self.client.post(
            "/auth/dev-login",
            json={"phone": "+79997776655"},
        )
        self.assertEqual(response.status_code, 200)
        user = response.json()["data"]["user"]
        self.assertEqual(user["phone"], "+79997776655")
        self.assertEqual(user["verificationStatus"], "draft")

    async def test_dev_login_existing_user(self):
        """dev-login works for an already registered user."""
        # First login — creates user
        await self.client.post("/auth/dev-login", json={"phone": "+79991112233"})
        # Second login — same user
        response = await self.client.post(
            "/auth/dev-login", json={"phone": "+79991112233"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("accessToken", response.json()["data"])

    async def test_dev_login_missing_phone(self):
        """dev-login without phone returns 422."""
        response = await self.client.post("/auth/dev-login", json={})
        self.assertEqual(response.status_code, 422)

    async def test_dev_login_empty_phone(self):
        """dev-login with empty phone string returns 422."""
        response = await self.client.post(
            "/auth/dev-login", json={"phone": ""}
        )
        self.assertEqual(response.status_code, 422)

    # ------------------------------------------------------------------
    # 2. request-code: should work without sending SMS
    # ------------------------------------------------------------------

    async def test_request_code_no_sms_sent(self):
        """POST /auth/request-code creates session without sending SMS."""
        with patch("backend.routers.auth.send_auth_code") as mock_sms:
            response = await self.client.post(
                "/auth/request-code",
                json={"phone": "+79991234567"},
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("verificationSessionId", data)
        self.assertIn("ttlSeconds", data)
        # SMS should NOT have been called (it's commented out in the router)
        mock_sms.assert_not_called()

    # ------------------------------------------------------------------
    # 3. confirm-code: should accept any code (checks disabled)
    # ------------------------------------------------------------------

    async def test_confirm_code_any_code_accepted(self):
        """POST /auth/confirm-code accepts any code when checks are disabled."""
        # First, request a code to get a session ID
        req_response = await self.client.post(
            "/auth/request-code",
            json={"phone": "+79998887766"},
        )
        session_id = req_response.json()["data"]["verificationSessionId"]

        # Confirm with an arbitrary code — should succeed
        response = await self.client.post(
            "/auth/confirm-code",
            json={"verificationSessionId": session_id, "code": "0000"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("accessToken", data)
        self.assertIn("refreshToken", data)
        self.assertEqual(data["user"]["phone"], "+79998887766")

    # ------------------------------------------------------------------
    # 4. Full flow: phone → request-code → confirm-code → tokens
    # ------------------------------------------------------------------

    async def test_full_flow_request_then_confirm(self):
        """Full auth flow: request-code then confirm-code returns valid tokens."""
        phone = "+79995554433"

        # Step 1: request code
        req_response = await self.client.post(
            "/auth/request-code", json={"phone": phone}
        )
        self.assertEqual(req_response.status_code, 200)
        session_id = req_response.json()["data"]["verificationSessionId"]

        # Step 2: confirm code (any code works)
        confirm_response = await self.client.post(
            "/auth/confirm-code",
            json={"verificationSessionId": session_id, "code": "1234"},
        )
        self.assertEqual(confirm_response.status_code, 200)
        data = confirm_response.json()["data"]
        self.assertIn("accessToken", data)
        self.assertIn("refreshToken", data)
        self.assertEqual(data["user"]["phone"], phone)

        # Step 3: verify access token works (call /health as sanity check)
        health = await self.client.get("/health")
        self.assertEqual(health.status_code, 200)

    # ------------------------------------------------------------------
    # 5. Token refresh works after login
    # ------------------------------------------------------------------

    async def test_refresh_after_dev_login(self):
        """Refresh token obtained from dev-login can be used to get new access token."""
        login_response = await self.client.post(
            "/auth/dev-login", json={"phone": "+79990001122"}
        )
        refresh_token = login_response.json()["data"]["refreshToken"]

        refresh_response = await self.client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        self.assertEqual(refresh_response.status_code, 200)
        data = refresh_response.json()["data"]
        self.assertIn("accessToken", data)

    # ------------------------------------------------------------------
    # 6. Logout works after login
    # ------------------------------------------------------------------

    async def test_logout_after_dev_login(self):
        """Logout with access token from dev-login succeeds."""
        login_response = await self.client.post(
            "/auth/dev-login", json={"phone": "+79990009988"}
        )
        access_token = login_response.json()["data"]["accessToken"]

        logout_response = await self.client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.assertEqual(logout_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
