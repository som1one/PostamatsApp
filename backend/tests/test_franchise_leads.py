"""Тесты публичной заявки на франшизу (backend/routers/franchise_leads.py).

Проверяем то, ради чего эндпоинт существует: заявка сохраняется в раздел
«Обратная связь» и уходит админам в мессенджеры, телефон приводится к
набираемому виду, пользовательский текст экранируется, а публичную ручку
нельзя превратить в спам-пушку.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from backend.core.database import Base
from backend.models.feedback_message import FeedbackMessage
from backend.models.media_file import MediaFile
from backend.routers import franchise_leads
from backend.routers.franchise_leads import (
    FranchiseLeadPayload,
    create_franchise_lead,
)

TEST_DB_URL = "sqlite+aiosqlite:///test_franchise_leads.sqlite"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)

TEST_TABLES = [MediaFile.__table__, FeedbackMessage.__table__]


def _request(ip: str = "203.0.113.10", forwarded: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/franchise/leads",
            "headers": headers,
            "client": (ip, 51234),
        }
    )


class FranchiseLeadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        async with test_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=TEST_TABLES)
            )
        # Лимитер живёт в модуле, между тестами его надо обнулять.
        franchise_leads._limiter.reset()

    async def asyncTearDown(self) -> None:
        async with test_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.drop_all(sync_conn, tables=TEST_TABLES)
            )

    async def _create(self, notify: AsyncMock, request: Request, **payload) -> dict:
        data = {"name": "Иван", "phone": "+79001234567"} | payload
        async with TestSessionLocal() as db:
            with patch.object(franchise_leads, "notify_admins", notify):
                return await create_franchise_lead(
                    request, FranchiseLeadPayload(**data), db
                )

    async def _submit(self, notify: AsyncMock, **payload) -> dict:
        return await self._create(notify, _request(), **payload)

    async def _stored(self) -> list[FeedbackMessage]:
        async with TestSessionLocal() as db:
            rows = await db.execute(
                select(FeedbackMessage).order_by(FeedbackMessage.created_at)
            )
            return list(rows.scalars())

    async def test_lead_goes_to_messengers(self) -> None:
        notify = AsyncMock(return_value=2)
        result = await self._submit(notify, city="Псков")

        self.assertEqual(result["data"]["delivered"], 2)
        notify.assert_awaited_once()
        text = notify.await_args.args[0]
        self.assertIn("Заявка на франшизу", text)
        self.assertIn("Иван", text)
        self.assertIn("+79001234567", text)
        self.assertIn("Псков", text)

    async def test_lead_is_stored_in_feedback_inbox(self) -> None:
        notify = AsyncMock(return_value=1)
        result = await self._submit(notify, city="Псков", comment="Хочу франшизу", source="web")

        stored = await self._stored()
        self.assertEqual(len(stored), 1)
        record = stored[0]
        self.assertEqual(str(record.id), result["data"]["id"])
        self.assertEqual(record.topic, "franchise")
        self.assertEqual(record.source, "web")
        self.assertEqual(record.phone, "+79001234567")
        self.assertEqual(record.city, "Псков")
        self.assertEqual(record.message, "Хочу франшизу")
        self.assertIsNone(record.email)
        # Источник видно и в уведомлении, не только в карточке.
        self.assertIn("Сайт", notify.await_args.args[0])

    async def test_unknown_source_is_not_guessed(self) -> None:
        notify = AsyncMock(return_value=1)
        await self._submit(notify)

        stored = await self._stored()
        self.assertEqual(stored[0].source, "unknown")
        self.assertIn("Источник не определён", notify.await_args.args[0])

    async def test_city_and_comment_are_optional(self) -> None:
        notify = AsyncMock(return_value=1)
        await self._submit(notify, city="   ", comment=None)

        text = notify.await_args.args[0]
        self.assertIn("+79001234567", text)
        self.assertNotIn("🏙", text)

    async def test_russian_phone_is_normalized(self) -> None:
        notify = AsyncMock(return_value=1)
        await self._submit(notify, phone="8 (900) 123-45-67")
        self.assertIn("+79001234567", notify.await_args.args[0])

        notify_short = AsyncMock(return_value=1)
        await self._submit(notify_short, phone="9001234567")
        self.assertIn("+79001234567", notify_short.await_args.args[0])

    async def test_broken_phone_is_rejected(self) -> None:
        notify = AsyncMock(return_value=1)
        for bad in ("123", "12345", "телефон", "+7900123456789012"):
            with self.subTest(phone=bad):
                franchise_leads._limiter.reset()
                with self.assertRaises(HTTPException) as ctx:
                    await self._submit(notify, phone=bad)
                self.assertEqual(ctx.exception.status_code, 400)
                self.assertEqual(ctx.exception.detail, "INVALID_PHONE")
        notify.assert_not_awaited()
        self.assertEqual(await self._stored(), [])

    async def test_user_text_is_html_escaped(self) -> None:
        notify = AsyncMock(return_value=1)
        await self._submit(
            notify, name="<b>Иван</b>", comment="<script>alert(1)</script>"
        )

        text = notify.await_args.args[0]
        self.assertIn("&lt;b&gt;Иван&lt;/b&gt;", text)
        self.assertNotIn("<script>", text)

    async def test_per_ip_rate_limit(self) -> None:
        notify = AsyncMock(return_value=1)
        for _ in range(franchise_leads._limiter.per_ip):
            await self._submit(notify)

        with self.assertRaises(HTTPException) as ctx:
            await self._submit(notify)
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail, "TOO_MANY_REQUESTS")

        # Другой IP лимитом соседа не задет.
        await self._create(
            notify,
            _request(forwarded="198.51.100.7"),
            name="Пётр",
            phone="+79007654321",
        )
        self.assertEqual(notify.await_count, franchise_leads._limiter.per_ip + 1)

    async def test_global_rate_limit(self) -> None:
        notify = AsyncMock(return_value=1)
        for index in range(franchise_leads._limiter.global_limit):
            await self._create(notify, _request(forwarded=f"198.51.100.{index}"))

        with self.assertRaises(HTTPException) as ctx:
            await self._create(notify, _request(forwarded="198.51.100.200"))
        self.assertEqual(ctx.exception.status_code, 429)

    async def test_undelivered_lead_still_answers_ok(self) -> None:
        notify = AsyncMock(return_value=0)
        result = await self._submit(notify)
        self.assertEqual(result["data"]["delivered"], 0)
        # Не доехало до мессенджеров — но лид сохранён и виден в админке.
        self.assertEqual(len(await self._stored()), 1)


if __name__ == "__main__":
    unittest.main()
