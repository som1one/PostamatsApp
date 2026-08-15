"""Раздел «Обратная связь»: приём обращений и их выдача в админку.

Проверяем главное, ради чего раздел переделан:

1. Обращение с любой формы (сайт, приложение) сохраняется в одну таблицу.
2. Источник фиксируется честно: клиент прислал ``web``/``mobile`` — так и
   пишем, прислал мусор или ничего — ``unknown``, а не «сайт».
3. Уведомление уходит и в Telegram, и в MAX (один вызов
   ``fire_and_forget_notify``) и содержит тип обращения и источник.
4. Админский список отдаёт готовые подписи для карточки.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from backend.core.database import Base
from backend.models.feedback_message import FeedbackMessage
from backend.models.media_file import MediaFile
from backend.routers import feedback as feedback_router
from backend.routers.admin import feedback as admin_feedback_router
from backend.routers.feedback import FeedbackCreatePayload, create_feedback

TEST_DB_URL = "sqlite+aiosqlite:///test_feedback_inbox.sqlite"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)

TEST_TABLES = [MediaFile.__table__, FeedbackMessage.__table__]


def _request(ip: str = "203.0.113.10") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/feedback",
            "headers": [],
            "client": (ip, 51234),
        }
    )


class FeedbackInboxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        async with test_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=TEST_TABLES)
            )
        feedback_router._limiter.reset()

    async def asyncTearDown(self) -> None:
        async with test_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.drop_all(sync_conn, tables=TEST_TABLES)
            )

    async def _submit(self, notify, ip: str = "203.0.113.10", **payload) -> dict:
        data = {
            "name": "Иван",
            "email": "ivan@example.com",
            "message": "Добавьте палатку",
        } | payload
        async with TestSessionLocal() as db:
            with patch.object(feedback_router, "notify_feedback_created", notify):
                return await create_feedback(
                    _request(ip), FeedbackCreatePayload(**data), db
                )

    async def _stored(self) -> list[FeedbackMessage]:
        async with TestSessionLocal() as db:
            rows = await db.execute(
                select(FeedbackMessage).order_by(FeedbackMessage.created_at)
            )
            return list(rows.scalars())

    async def test_web_idea_is_stored_with_source(self) -> None:
        notify = Mock()
        result = await self._submit(notify, source="web", referenceUrl="https://example.com/tent")

        stored = await self._stored()
        self.assertEqual(len(stored), 1)
        record = stored[0]
        self.assertEqual(str(record.id), result["data"]["id"])
        self.assertEqual(record.topic, "idea")
        self.assertEqual(record.source, "web")
        self.assertEqual(record.email, "ivan@example.com")
        self.assertEqual(record.message, "Добавьте палатку")
        self.assertEqual(record.reference_url, "https://example.com/tent")
        notify.assert_called_once()

    async def test_mobile_source_is_kept(self) -> None:
        notify = Mock()
        await self._submit(notify, source="mobile")
        self.assertEqual((await self._stored())[0].source, "mobile")

    async def test_unknown_source_is_not_guessed(self) -> None:
        notify = Mock()
        await self._submit(notify)
        await self._submit(notify, source="carrier-pigeon")

        self.assertEqual([record.source for record in await self._stored()], ["unknown"] * 2)

    async def test_legacy_idea_field_is_accepted(self) -> None:
        """Установленные сборки приложения шлют поле ``idea`` — принимаем."""

        notify = Mock()
        await self._submit(notify, message=None, idea="Ролики 42 размера")
        self.assertEqual((await self._stored())[0].message, "Ролики 42 размера")

    async def test_broken_email_is_rejected(self) -> None:
        notify = Mock()
        with self.assertRaises(HTTPException) as ctx:
            await self._submit(notify, email="не-почта")
        self.assertEqual(ctx.exception.detail, "INVALID_EMAIL")
        self.assertEqual(await self._stored(), [])
        notify.assert_not_called()

    async def test_rate_limit_protects_the_public_form(self) -> None:
        notify = Mock()
        for _ in range(feedback_router._limiter.per_ip):
            await self._submit(notify)

        with self.assertRaises(HTTPException) as ctx:
            await self._submit(notify)
        self.assertEqual(ctx.exception.status_code, 429)

    async def test_notification_names_topic_and_source(self) -> None:
        from backend.utils import feedback_notifications

        record = FeedbackMessage(
            id=uuid4(),
            topic="idea",
            source="mobile",
            name="Иван",
            email="ivan@example.com",
            message="Добавьте палатку",
            created_at=datetime.now(timezone.utc),
        )
        text, buttons = feedback_notifications.build_feedback_notification(record)

        self.assertIn("Идея для аренды", text)
        self.assertIn("Мобильное приложение", text)
        self.assertIn("Добавьте палатку", text)
        # Кнопка ведёт в раздел обратной связи — если админский URL настроен.
        for label, url in buttons:
            self.assertEqual(label, "Открыть в админке")
            self.assertIn("section=feedback", url)

    async def test_notification_goes_to_both_channels(self) -> None:
        """Уведомление отдаём общему транспорту — он шлёт в Telegram и MAX."""

        from backend.utils import feedback_notifications

        fired = Mock()
        with patch.object(feedback_notifications, "fire_and_forget_notify", fired):
            feedback_notifications.notify_feedback_created(
                FeedbackMessage(
                    id=uuid4(),
                    topic="idea",
                    source="web",
                    name="Иван",
                    email="ivan@example.com",
                    message="Добавьте палатку",
                    created_at=datetime.now(timezone.utc),
                )
            )
        fired.assert_called_once()
        self.assertIn("Идея для аренды", fired.call_args.args[0])

    async def test_admin_list_labels_topic_and_source(self) -> None:
        notify = Mock()
        await self._submit(notify, source="mobile")

        async with TestSessionLocal() as db:
            with patch.object(
                admin_feedback_router, "get_current_admin", AsyncMock(return_value=None)
            ):
                payload = await admin_feedback_router.list_feedback(
                    _request(), db, page=1, limit=50, topic=None
                )

        items = payload["data"]["items"]
        self.assertEqual(payload["data"]["total"], 1)
        self.assertEqual(items[0]["sourceLabel"], "Мобильное приложение")
        self.assertEqual(items[0]["topicLabel"], "Идея для аренды")
        self.assertEqual(items[0]["message"], "Добавьте палатку")

    async def test_admin_list_filters_by_topic(self) -> None:
        notify = Mock()
        await self._submit(notify, source="web")

        async with TestSessionLocal() as db:
            with patch.object(
                admin_feedback_router, "get_current_admin", AsyncMock(return_value=None)
            ):
                payload = await admin_feedback_router.list_feedback(
                    _request(), db, page=1, limit=50, topic="franchise"
                )
        self.assertEqual(payload["data"]["items"], [])
        self.assertEqual(payload["data"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
