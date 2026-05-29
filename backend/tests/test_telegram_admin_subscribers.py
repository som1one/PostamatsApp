"""Юнит-тесты CRUD и resync для Telegram-подписчиков.

Покрытие:

- normalize_username принимает и нормализует валидные ники,
  отклоняет невалидные.
- create / list / update / delete — корректно сохраняют состояние и
  валидируют конфликты.
- get_active_chat_ids возвращает только включённых и привязанных.
- ensure_default_subscribers создаёт ``som1ones`` при первом запуске и
  идемпотентен при повторе.
- resync_chat_ids матчит username → chat_id из мокнутого Telegram API
  и не перезаписывает уже привязанные значения.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("UPLOAD_DEV_STUB", "true")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.core.settings import settings
from backend.models.telegram_admin_subscriber import TelegramAdminSubscriber  # noqa: F401
from backend.utils.telegram_admin_subscribers import (
    SubscriberError,
    create_subscriber,
    delete_subscriber,
    ensure_default_subscribers,
    get_active_chat_ids,
    list_subscribers,
    normalize_username,
    resync_chat_ids,
    update_subscriber,
)


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "fake"

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str, params: dict | None = None):
        self.calls.append((url, params or {}))
        return self._response


class NormalizeUsernameTests(unittest.TestCase):
    def test_strips_at_and_lowercases(self) -> None:
        self.assertEqual(normalize_username("@SoM1OneS"), "som1ones")

    def test_rejects_short(self) -> None:
        with self.assertRaises(SubscriberError) as ctx:
            normalize_username("@abc")
        self.assertEqual(ctx.exception.code, "USERNAME_INVALID")

    def test_rejects_invalid_chars(self) -> None:
        with self.assertRaises(SubscriberError):
            normalize_username("bad-name!")

    def test_rejects_empty(self) -> None:
        with self.assertRaises(SubscriberError) as ctx:
            normalize_username("")
        self.assertEqual(ctx.exception.code, "USERNAME_REQUIRED")

    def test_rejects_leading_digit(self) -> None:
        with self.assertRaises(SubscriberError):
            normalize_username("9some_user")


class TelegramSubscribersDbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(TEST_DB_URL, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_create_list_update_delete(self) -> None:
        async with self.SessionLocal() as db:
            sub = await create_subscriber(db, username="@SoM1OneS", note=" main ")
            self.assertEqual(sub.username, "som1ones")
            self.assertTrue(sub.is_enabled)
            self.assertIsNone(sub.chat_id)

            with self.assertRaises(SubscriberError) as ctx:
                await create_subscriber(db, username="som1ones")
            self.assertEqual(ctx.exception.code, "SUBSCRIBER_ALREADY_EXISTS")

            updated = await update_subscriber(
                db, sub.id, is_enabled=False, note=""
            )
            self.assertFalse(updated.is_enabled)
            self.assertIsNone(updated.note)

            rows = await list_subscribers(db)
            self.assertEqual([r.username for r in rows], ["som1ones"])

            await delete_subscriber(db, sub.id)
            rows = await list_subscribers(db)
            self.assertEqual(rows, [])

    async def test_get_active_chat_ids_filters_disabled_and_unlinked(self) -> None:
        async with self.SessionLocal() as db:
            disabled = await create_subscriber(db, username="off_user")
            await update_subscriber(db, disabled.id, is_enabled=False)

            unlinked = await create_subscriber(db, username="pending_user")
            self.assertIsNone(unlinked.chat_id)

            linked = await create_subscriber(db, username="linked_user")
            linked.chat_id = 555
            await db.commit()

            ids = await get_active_chat_ids(db)
            self.assertEqual(ids, ["555"])

    async def test_ensure_default_subscribers_is_idempotent(self) -> None:
        async with self.SessionLocal() as db:
            await ensure_default_subscribers(db)
            await ensure_default_subscribers(db)
            rows = await list_subscribers(db)

        usernames = [r.username for r in rows]
        self.assertEqual(sorted(usernames), ["som1ones"])

    async def test_resync_links_only_unlinked(self) -> None:
        async with self.SessionLocal() as db:
            already_linked = await create_subscriber(db, username="known")
            already_linked.chat_id = 111
            await db.commit()

            await create_subscriber(db, username="newcomer")
            await create_subscriber(db, username="ghost")

        # newcomer прислал /start, ghost — нет, known уже привязан и
        # не должен меняться.
        fake_response = _FakeResponse(
            200,
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 1,
                        "message": {
                            "chat": {"id": 222, "username": "Newcomer"},
                        },
                    },
                    {
                        "update_id": 2,
                        "message": {
                            "chat": {"id": 999, "username": "known"},
                        },
                    },
                ],
            },
        )
        fake_client = _FakeAsyncClient(fake_response)

        old_token = settings.TELEGRAM_ADMIN_BOT_TOKEN
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "111:secret"
        try:
            with patch(
                "backend.utils.telegram_admin_subscribers.httpx.AsyncClient",
                return_value=fake_client,
            ):
                async with self.SessionLocal() as db:
                    report = await resync_chat_ids(db)
        finally:
            settings.TELEGRAM_ADMIN_BOT_TOKEN = old_token

        self.assertEqual(report["linked"], 1)
        self.assertEqual(report["alreadyLinked"], 1)
        self.assertEqual(report["missing"], ["ghost"])
        self.assertEqual(report["updatesSeen"], 2)

        async with self.SessionLocal() as db:
            rows = {row.username: row.chat_id for row in await list_subscribers(db)}
        # known не перезаписан; newcomer привязан; ghost остался без chat_id.
        self.assertEqual(rows["known"], 111)
        self.assertEqual(rows["newcomer"], 222)
        self.assertIsNone(rows["ghost"])

    async def test_resync_without_token_raises(self) -> None:
        old_token = settings.TELEGRAM_ADMIN_BOT_TOKEN
        settings.TELEGRAM_ADMIN_BOT_TOKEN = None
        try:
            async with self.SessionLocal() as db:
                with self.assertRaises(SubscriberError) as ctx:
                    await resync_chat_ids(db)
            self.assertEqual(
                ctx.exception.code, "TELEGRAM_BOT_TOKEN_NOT_CONFIGURED"
            )
        finally:
            settings.TELEGRAM_ADMIN_BOT_TOKEN = old_token


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Webhook /start handler
# ---------------------------------------------------------------------------


class TelegramStartHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(TEST_DB_URL, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )
        self._old_token = settings.TELEGRAM_ADMIN_BOT_TOKEN
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "111:secret"

    async def asyncTearDown(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = self._old_token
        await self.engine.dispose()

    async def _run(self, db, update):
        from backend.utils.telegram_admin_subscribers import (
            handle_telegram_update,
        )

        sent: list[tuple[int, str]] = []

        async def fake_send(chat_id: int, text: str) -> None:
            sent.append((chat_id, text))

        with patch(
            "backend.utils.telegram_admin_subscribers._send_message",
            side_effect=fake_send,
        ):
            result = await handle_telegram_update(db, update)
        return result, sent

    async def test_start_links_existing_subscriber_and_replies(self) -> None:
        async with self.SessionLocal() as db:
            sub = await create_subscriber(db, username="som1ones")
            self.assertIsNone(sub.chat_id)

        update = {
            "message": {
                "text": "/start",
                "chat": {"id": 123456, "username": "Som1Ones", "type": "private"},
            }
        }
        async with self.SessionLocal() as db:
            result, sent = await self._run(db, update)

        self.assertEqual(result["handled"], True)
        self.assertEqual(result["reason"], "linked")
        self.assertEqual(sent, [(123456, _import_welcome_message())])

        async with self.SessionLocal() as db:
            rows = await list_subscribers(db)
        self.assertEqual(rows[0].chat_id, 123456)

    async def test_start_for_unknown_username_does_not_create(self) -> None:
        update = {
            "message": {
                "text": "/start",
                "chat": {"id": 999, "username": "stranger", "type": "private"},
            }
        }
        async with self.SessionLocal() as db:
            result, sent = await self._run(db, update)

        self.assertEqual(result["reason"], "not_in_allowlist")
        self.assertEqual(len(sent), 1)

        async with self.SessionLocal() as db:
            rows = await list_subscribers(db)
        self.assertEqual(rows, [])

    async def test_non_start_message_is_ignored(self) -> None:
        update = {
            "message": {
                "text": "привет",
                "chat": {"id": 111, "username": "som1ones", "type": "private"},
            }
        }
        async with self.SessionLocal() as db:
            result, sent = await self._run(db, update)
        self.assertEqual(result["handled"], False)
        self.assertEqual(sent, [])

    async def test_start_without_username_replies_with_hint(self) -> None:
        update = {
            "message": {
                "text": "/start",
                "chat": {"id": 222, "type": "private"},
            }
        }
        async with self.SessionLocal() as db:
            result, sent = await self._run(db, update)
        self.assertEqual(result["reason"], "no_username")
        self.assertEqual(len(sent), 1)


def _import_welcome_message() -> str:
    from backend.utils.telegram_admin_subscribers import WELCOME_MESSAGE

    return WELCOME_MESSAGE


class WebhookUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_secret = settings.TELEGRAM_WEBHOOK_SECRET
        self._old_admin = settings.ADMIN_PANEL_URL

    def tearDown(self) -> None:
        settings.TELEGRAM_WEBHOOK_SECRET = self._old_secret
        settings.ADMIN_PANEL_URL = self._old_admin

    def test_prefers_admin_panel_url_and_strips_admin_suffix(self) -> None:
        from backend.utils.telegram_admin_subscribers import _webhook_url

        settings.TELEGRAM_WEBHOOK_SECRET = "sek"
        settings.ADMIN_PANEL_URL = "https://api.example.ru/admin"
        url = _webhook_url("https://ignored.example/")
        self.assertEqual(url, "https://api.example.ru/telegram/webhook/sek")

    def test_falls_back_to_request_origin_when_admin_url_empty(self) -> None:
        from backend.utils.telegram_admin_subscribers import _webhook_url

        settings.TELEGRAM_WEBHOOK_SECRET = "sek"
        settings.ADMIN_PANEL_URL = None
        url = _webhook_url("https://api.example.ru/")
        self.assertEqual(url, "https://api.example.ru/telegram/webhook/sek")

    def test_raises_without_secret(self) -> None:
        from backend.utils.telegram_admin_subscribers import _webhook_url

        settings.TELEGRAM_WEBHOOK_SECRET = None
        with self.assertRaises(SubscriberError) as ctx:
            _webhook_url("https://api.example.ru/")
        self.assertEqual(ctx.exception.code, "TELEGRAM_WEBHOOK_SECRET_NOT_CONFIGURED")

    def test_raises_without_any_base(self) -> None:
        from backend.utils.telegram_admin_subscribers import _webhook_url

        settings.TELEGRAM_WEBHOOK_SECRET = "sek"
        settings.ADMIN_PANEL_URL = None
        with self.assertRaises(SubscriberError) as ctx:
            _webhook_url(None)
        self.assertEqual(ctx.exception.code, "TELEGRAM_WEBHOOK_BASE_URL_REQUIRED")
