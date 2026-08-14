"""Юнит-тесты CRUD, resync и webhook-обработчика для MAX-подписчиков.

Покрытие:

- normalize_username принимает и нормализует валидные ники, отклоняет мусор.
- create / list / update / delete — состояние и конфликты.
- get_active_recipients отдаёт только включённых и связанных, предпочитая
  chat_id перед user_id.
- ensure_default_subscribers идемпотентен.
- parse_update разбирает обе формы апдейта (bot_started и message_created).
- resync_chat_ids матчит username → идентификаторы диалога из мокнутого
  MAX API и не перезаписывает уже связанных.
- handle_max_update связывает подписчика при запуске бота и игнорирует
  всё остальное.
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
from backend.models.city import City  # noqa: F401
from backend.models.max_admin_subscriber import MaxAdminSubscriber  # noqa: F401
from backend.utils.max_admin_subscribers import (
    SubscriberError,
    create_subscriber,
    delete_subscriber,
    ensure_default_subscribers,
    get_active_recipients,
    list_subscribers,
    normalize_username,
    parse_update,
    resync_chat_ids,
    update_subscriber,
)

# Создаём только таблицу подписчиков, чтобы при совместном прогоне с
# другими тестами не тянуть весь граф моделей.
# Города нужны из-за FK city_id (адресация уведомлений по городу).
SUBSCRIBER_TABLES = [City.__table__, MaxAdminSubscriber.__table__]

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

BOT_STARTED_UPDATE = {
    "update_type": "bot_started",
    "timestamp": 1_700_000_000_000,
    "chat_id": 222,
    "user": {"user_id": 22, "username": "Newcomer", "first_name": "N"},
    "user_locale": "ru",
}

MESSAGE_CREATED_UPDATE = {
    "update_type": "message_created",
    "timestamp": 1_700_000_000_001,
    "message": {
        "sender": {"user_id": 99, "username": "known", "first_name": "K"},
        "recipient": {"chat_id": 999, "chat_type": "dialog"},
        "body": {"mid": "mid-1", "seq": 1, "text": "/start"},
    },
}


async def _create_subscriber_tables(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=SUBSCRIBER_TABLES
            )
        )


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
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._response


class NormalizeUsernameTests(unittest.TestCase):
    def test_strips_at_and_lowercases(self) -> None:
        self.assertEqual(normalize_username("@SoM1OneS"), "som1ones")

    def test_rejects_short(self) -> None:
        with self.assertRaises(SubscriberError) as ctx:
            normalize_username("@abc")
        self.assertEqual(ctx.exception.code, "USERNAME_INVALID")

    def test_rejects_empty(self) -> None:
        with self.assertRaises(SubscriberError) as ctx:
            normalize_username("")
        self.assertEqual(ctx.exception.code, "USERNAME_REQUIRED")


class ParseUpdateTests(unittest.TestCase):
    def test_bot_started(self) -> None:
        parsed = parse_update(BOT_STARTED_UPDATE)
        self.assertEqual(parsed.username, "newcomer")
        self.assertEqual(parsed.chat_id, 222)
        self.assertEqual(parsed.user_id, 22)
        self.assertTrue(parsed.is_start)
        self.assertEqual(parsed.recipient, ("chat_id", 222))

    def test_message_created_start(self) -> None:
        parsed = parse_update(MESSAGE_CREATED_UPDATE)
        self.assertEqual(parsed.username, "known")
        self.assertEqual(parsed.chat_id, 999)
        self.assertEqual(parsed.user_id, 99)
        self.assertTrue(parsed.is_start)

    def test_plain_message_is_not_start(self) -> None:
        update = {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 1, "username": "som1ones"},
                "recipient": {"chat_id": 2},
                "body": {"text": "привет"},
            },
        }
        self.assertFalse(parse_update(update).is_start)

    def test_garbage_does_not_raise(self) -> None:
        parsed = parse_update({"update_type": "message_created", "message": "wat"})
        self.assertIsNone(parsed.username)
        self.assertIsNone(parsed.recipient)


class MaxSubscribersDbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(TEST_DB_URL, echo=False)
        await _create_subscriber_tables(self.engine)
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
            self.assertIsNone(sub.user_id)

            with self.assertRaises(SubscriberError) as ctx:
                await create_subscriber(db, username="som1ones")
            self.assertEqual(ctx.exception.code, "SUBSCRIBER_ALREADY_EXISTS")

            updated = await update_subscriber(db, sub.id, is_enabled=False, note="")
            self.assertFalse(updated.is_enabled)
            self.assertIsNone(updated.note)

            await delete_subscriber(db, sub.id)
            self.assertEqual(await list_subscribers(db), [])

    async def test_get_active_recipients_filters_and_prefers_chat(self) -> None:
        async with self.SessionLocal() as db:
            disabled = await create_subscriber(db, username="off_user")
            disabled.chat_id = 1
            await update_subscriber(db, disabled.id, is_enabled=False)

            await create_subscriber(db, username="pending_user")

            by_chat = await create_subscriber(db, username="chat_user")
            by_chat.chat_id = 555
            by_chat.user_id = 55

            by_user = await create_subscriber(db, username="user_only")
            by_user.user_id = 66
            await db.commit()

            recipients = await get_active_recipients(db)

        self.assertEqual(
            sorted(recipients), sorted([("chat_id", 555), ("user_id", 66)])
        )

    async def test_ensure_default_subscribers_is_idempotent(self) -> None:
        async with self.SessionLocal() as db:
            await ensure_default_subscribers(db)
            await ensure_default_subscribers(db)
            rows = await list_subscribers(db)

        self.assertEqual([r.username for r in rows], ["som1ones"])

    async def test_resync_links_only_unlinked(self) -> None:
        async with self.SessionLocal() as db:
            already_linked = await create_subscriber(db, username="known")
            already_linked.chat_id = 111
            await db.commit()

            await create_subscriber(db, username="newcomer")
            await create_subscriber(db, username="ghost")

        fake_client = _FakeAsyncClient(
            _FakeResponse(
                200,
                {
                    "updates": [BOT_STARTED_UPDATE, MESSAGE_CREATED_UPDATE],
                    "marker": 7,
                },
            )
        )

        old_token = settings.MAX_ADMIN_BOT_TOKEN
        settings.MAX_ADMIN_BOT_TOKEN = "max-token"
        try:
            with patch(
                "backend.utils.max_admin_subscribers.httpx.AsyncClient",
                return_value=fake_client,
            ):
                async with self.SessionLocal() as db:
                    report = await resync_chat_ids(db)
        finally:
            settings.MAX_ADMIN_BOT_TOKEN = old_token

        self.assertEqual(report["linked"], 1)
        self.assertEqual(report["alreadyLinked"], 1)
        self.assertEqual(report["missing"], ["ghost"])
        self.assertEqual(report["updatesSeen"], 2)

        async with self.SessionLocal() as db:
            rows = {row.username: row for row in await list_subscribers(db)}
        # known не перезаписан; newcomer связан по bot_started; ghost пуст.
        self.assertEqual(rows["known"].chat_id, 111)
        self.assertEqual(rows["newcomer"].chat_id, 222)
        self.assertEqual(rows["newcomer"].user_id, 22)
        self.assertIsNone(rows["ghost"].chat_id)
        self.assertIsNone(rows["ghost"].user_id)

    async def test_resync_without_token_raises(self) -> None:
        old_token = settings.MAX_ADMIN_BOT_TOKEN
        settings.MAX_ADMIN_BOT_TOKEN = None
        try:
            async with self.SessionLocal() as db:
                with self.assertRaises(SubscriberError) as ctx:
                    await resync_chat_ids(db)
            self.assertEqual(ctx.exception.code, "MAX_BOT_TOKEN_NOT_CONFIGURED")
        finally:
            settings.MAX_ADMIN_BOT_TOKEN = old_token


class MaxStartHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(TEST_DB_URL, echo=False)
        await _create_subscriber_tables(self.engine)
        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )
        self._old_token = settings.MAX_ADMIN_BOT_TOKEN
        settings.MAX_ADMIN_BOT_TOKEN = "max-token"

    async def asyncTearDown(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = self._old_token
        await self.engine.dispose()

    async def _run(self, db, update):
        from backend.utils.max_admin_subscribers import handle_max_update

        sent: list[tuple[tuple[str, int], str]] = []

        async def fake_send(recipient, text: str) -> None:
            sent.append((recipient, text))

        with patch(
            "backend.utils.max_admin_subscribers._send_message",
            side_effect=fake_send,
        ):
            result = await handle_max_update(db, update)
        return result, sent

    async def test_bot_started_links_existing_subscriber(self) -> None:
        from backend.utils.max_admin_subscribers import WELCOME_MESSAGE

        async with self.SessionLocal() as db:
            await create_subscriber(db, username="newcomer")

        async with self.SessionLocal() as db:
            result, sent = await self._run(db, BOT_STARTED_UPDATE)

        self.assertEqual(result, {"handled": True, "reason": "linked"})
        self.assertEqual(sent, [(("chat_id", 222), WELCOME_MESSAGE)])

        async with self.SessionLocal() as db:
            row = (await list_subscribers(db))[0]
        self.assertEqual(row.chat_id, 222)
        self.assertEqual(row.user_id, 22)

    async def test_start_for_unknown_username_does_not_create(self) -> None:
        async with self.SessionLocal() as db:
            result, sent = await self._run(db, MESSAGE_CREATED_UPDATE)

        self.assertEqual(result["reason"], "not_in_allowlist")
        self.assertEqual(len(sent), 1)

        async with self.SessionLocal() as db:
            self.assertEqual(await list_subscribers(db), [])

    async def test_non_start_message_is_ignored(self) -> None:
        update = {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 1, "username": "som1ones"},
                "recipient": {"chat_id": 2},
                "body": {"text": "привет"},
            },
        }
        async with self.SessionLocal() as db:
            result, sent = await self._run(db, update)

        self.assertEqual(result, {"handled": False, "reason": "not_start"})
        self.assertEqual(sent, [])

    async def test_start_without_username_replies_with_hint(self) -> None:
        from backend.utils.max_admin_subscribers import NO_USERNAME_MESSAGE

        update = {
            "update_type": "bot_started",
            "chat_id": 333,
            "user": {"user_id": 33, "first_name": "Без ника"},
        }
        async with self.SessionLocal() as db:
            result, sent = await self._run(db, update)

        self.assertEqual(result["reason"], "no_username")
        self.assertEqual(sent, [(("chat_id", 333), NO_USERNAME_MESSAGE)])


class WebhookUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_secret = settings.MAX_WEBHOOK_SECRET
        self._old_admin = settings.ADMIN_PANEL_URL

    def tearDown(self) -> None:
        settings.MAX_WEBHOOK_SECRET = self._old_secret
        settings.ADMIN_PANEL_URL = self._old_admin

    def test_prefers_admin_panel_url_and_strips_admin_suffix(self) -> None:
        from backend.utils.max_admin_subscribers import _webhook_url

        settings.MAX_WEBHOOK_SECRET = "sek-ret"
        settings.ADMIN_PANEL_URL = "https://api.example.ru/admin"
        url = _webhook_url("https://ignored.example/")
        self.assertEqual(url, "https://api.example.ru/max/webhook/sek-ret")

    def test_falls_back_to_request_origin(self) -> None:
        from backend.utils.max_admin_subscribers import _webhook_url

        settings.MAX_WEBHOOK_SECRET = "sek-ret"
        settings.ADMIN_PANEL_URL = None
        url = _webhook_url("https://api.example.ru/")
        self.assertEqual(url, "https://api.example.ru/max/webhook/sek-ret")

    def test_raises_without_secret(self) -> None:
        from backend.utils.max_admin_subscribers import _webhook_url

        settings.MAX_WEBHOOK_SECRET = None
        with self.assertRaises(SubscriberError) as ctx:
            _webhook_url("https://api.example.ru/")
        self.assertEqual(ctx.exception.code, "MAX_WEBHOOK_SECRET_NOT_CONFIGURED")

    def test_rejects_secret_with_forbidden_chars(self) -> None:
        from backend.utils.max_admin_subscribers import _webhook_url

        # MAX разрешает в секрете только латиницу, цифры и дефис.
        settings.MAX_WEBHOOK_SECRET = "se_kret!"
        settings.ADMIN_PANEL_URL = "https://api.example.ru/admin"
        with self.assertRaises(SubscriberError) as ctx:
            _webhook_url(None)
        self.assertEqual(ctx.exception.code, "MAX_WEBHOOK_SECRET_INVALID")

    def test_raises_without_any_base(self) -> None:
        from backend.utils.max_admin_subscribers import _webhook_url

        settings.MAX_WEBHOOK_SECRET = "sek-ret"
        settings.ADMIN_PANEL_URL = None
        with self.assertRaises(SubscriberError) as ctx:
            _webhook_url(None)
        self.assertEqual(ctx.exception.code, "MAX_WEBHOOK_BASE_URL_REQUIRED")


if __name__ == "__main__":
    unittest.main()
