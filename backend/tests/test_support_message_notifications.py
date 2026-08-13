"""Тесты телеграм-уведомлений о клиентских сообщениях в поддержку.

Сценарии:
1. Первое обращение → «Новое обращение в поддержку».
2. Follow-up в пределах кулдауна (пачка) → тишина.
3. Сообщение после кулдауна → «Новое сообщение в поддержку».
4. Сообщение в закрытый диалог → «Возобновлено обращение в поддержку».
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("UPLOAD_DEV_STUB", "true")

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.core.settings import settings
from backend.models.admin_account import AdminAccount
from backend.models.city import City
from backend.models.enums import ConversationStatus, VerificationStatus
from backend.models.support_conversation import SupportConversation
from backend.models.support_message import SupportMessage
from backend.models.user import User
from backend.services import support_chat_service
from backend.utils.support_notifications import notify_support_client_message

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

TEST_TABLES = [
    City.__table__,
    User.__table__,
    AdminAccount.__table__,
    SupportConversation.__table__,
    SupportMessage.__table__,
]


class SupportMessageNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(TEST_DB_URL, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=TEST_TABLES)
            )
        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _make_user(self, db: AsyncSession) -> User:
        user = User(
            id=uuid4(),
            phone="+79990000003",
            first_name="Иван",
            last_name="Тестов",
            verification_status=VerificationStatus.APPROVED,
        )
        db.add(user)
        await db.commit()
        return user

    def _notify(self, user: User, posted) -> MagicMock:
        """Вызывает notify_support_client_message с подменённой отправкой."""
        with (
            patch.object(settings, "WEB_APP_ORIGIN", "https://naprokatberu.ru"),
            patch(
                "backend.utils.support_notifications.fire_and_forget_notify"
            ) as sender,
        ):
            notify_support_client_message(
                user,
                posted.conversation,
                posted.message,
                conversation_was_created=posted.conversation_was_created,
                conversation_was_reopened=posted.conversation_was_reopened,
                previous_client_message_at=posted.previous_client_message_at,
            )
        return sender

    async def test_first_message_notifies_new_conversation(self) -> None:
        async with self.SessionLocal() as db:
            user = await self._make_user(db)
            posted = await support_chat_service.post_client_message_with_meta(
                db, user, "Здравствуйте, не открывается ячейка"
            )
            await db.commit()

        self.assertTrue(posted.conversation_was_created)
        self.assertIsNone(posted.previous_client_message_at)
        sender = self._notify(user, posted)
        sender.assert_called_once()
        text = sender.call_args.args[0]
        self.assertIn("Новое обращение в поддержку", text)
        self.assertIn("не открывается ячейка", text)

    async def test_burst_follow_up_is_silent(self) -> None:
        async with self.SessionLocal() as db:
            user = await self._make_user(db)
            first = await support_chat_service.post_client_message_with_meta(
                db, user, "Первое сообщение"
            )
            await db.commit()
            second = await support_chat_service.post_client_message_with_meta(
                db, user, "И сразу второе"
            )
            await db.commit()

        self.assertFalse(second.conversation_was_created)
        self.assertIsNotNone(second.previous_client_message_at)
        # Первое уведомило, второе (в пределах кулдауна) — молчит.
        self._notify(user, first).assert_called_once()
        self._notify(user, second).assert_not_called()

    async def test_message_after_cooldown_notifies(self) -> None:
        async with self.SessionLocal() as db:
            user = await self._make_user(db)
            await support_chat_service.post_client_message_with_meta(
                db, user, "Старое сообщение"
            )
            await db.commit()
            # Отодвигаем прошлое сообщение за пределы кулдауна.
            await db.execute(
                update(SupportMessage).values(
                    created_at=datetime.now(timezone.utc) - timedelta(minutes=15)
                )
            )
            await db.commit()

            posted = await support_chat_service.post_client_message_with_meta(
                db, user, "Вы тут? Ячейка так и не открылась"
            )
            await db.commit()

        self.assertFalse(posted.conversation_was_created)
        self.assertFalse(posted.conversation_was_reopened)
        sender = self._notify(user, posted)
        sender.assert_called_once()
        text = sender.call_args.args[0]
        self.assertIn("Новое сообщение в поддержку", text)
        self.assertIn("Ячейка так и не открылась", text)
        self.assertIn("Тестов Иван", text)
        # Кнопка ведёт в хелпер-панель на сайте: секции support в админке
        # нет, старая ссылка открывала пустую страницу.
        buttons = sender.call_args.kwargs.get("buttons") or []
        self.assertTrue(buttons, "у уведомления должна быть кнопка на диалог")
        label, url = buttons[0]
        self.assertEqual(label, "Открыть диалог")
        self.assertIn("/helperpanel?conversation=", url)
        self.assertIn(str(posted.conversation.id), url)

    async def test_widget_created_conversation_first_message_pings_once(self) -> None:
        """Виджет создал диалог при открытии (это уже пингует «Новое обращение»),
        первое сообщение секунды спустя не должно пинговать второй раз."""
        async with self.SessionLocal() as db:
            user = await self._make_user(db)
            # Как GET /api/support/conversation при открытии виджета.
            conversation, was_created = (
                await support_chat_service.get_or_create_conversation_with_meta(db, user)
            )
            await db.commit()
            self.assertTrue(was_created)

            posted = await support_chat_service.post_client_message_with_meta(
                db, user, "Первое сообщение после открытия виджета"
            )
            await db.commit()

        self.assertFalse(posted.conversation_was_created)
        self.assertIsNone(posted.previous_client_message_at)
        # Диалог свежий → рутинная ветка молчит (якорь — created_at диалога).
        self._notify(user, posted).assert_not_called()

    async def test_first_message_into_long_dormant_conversation_notifies(self) -> None:
        """Диалог создан давно (виджет открывали без сообщений) → первое
        реальное сообщение обязано пинговать."""
        async with self.SessionLocal() as db:
            user = await self._make_user(db)
            conversation, _ = (
                await support_chat_service.get_or_create_conversation_with_meta(db, user)
            )
            await db.commit()
            await db.execute(
                update(SupportConversation).values(
                    created_at=datetime.now(timezone.utc) - timedelta(days=2)
                )
            )
            await db.commit()
            await db.refresh(conversation)

            posted = await support_chat_service.post_client_message_with_meta(
                db, user, "Наконец-то пишу"
            )
            await db.commit()

        sender = self._notify(user, posted)
        sender.assert_called_once()
        self.assertIn("Новое сообщение в поддержку", sender.call_args.args[0])

    async def test_message_into_closed_conversation_notifies_reopen(self) -> None:
        async with self.SessionLocal() as db:
            user = await self._make_user(db)
            first = await support_chat_service.post_client_message_with_meta(
                db, user, "Первое сообщение"
            )
            await db.commit()
            first.conversation.status = ConversationStatus.CLOSED
            await db.commit()

            posted = await support_chat_service.post_client_message_with_meta(
                db, user, "Снова я"
            )
            await db.commit()

        self.assertTrue(posted.conversation_was_reopened)
        sender = self._notify(user, posted)
        sender.assert_called_once()
        self.assertIn("Возобновлено обращение", sender.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
