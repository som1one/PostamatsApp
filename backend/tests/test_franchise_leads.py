"""Тесты публичной заявки на франшизу (backend/routers/franchise_leads.py).

Проверяем то, ради чего эндпоинт существует: заявка уходит в Telegram,
телефон приводится к набираемому виду, пользовательский текст экранируется,
а публичную ручку нельзя превратить в спам-пушку.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

from backend.routers import franchise_leads
from backend.routers.franchise_leads import (
    FranchiseLeadPayload,
    create_franchise_lead,
)


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
    def setUp(self) -> None:
        # Лимитер живёт в модуле, между тестами его надо обнулять.
        franchise_leads._recent_by_ip.clear()
        franchise_leads._recent_global.clear()

    async def _submit(self, notify: AsyncMock, **payload) -> dict:
        data = {"name": "Иван", "phone": "+79001234567"} | payload
        with patch.object(franchise_leads, "notify_admins", notify):
            return await create_franchise_lead(
                _request(), FranchiseLeadPayload(**data)
            )

    async def test_lead_goes_to_telegram(self) -> None:
        notify = AsyncMock(return_value=2)
        result = await self._submit(notify, city="Псков")

        self.assertEqual(result, {"data": {"delivered": 2}})
        notify.assert_awaited_once()
        text = notify.await_args.args[0]
        self.assertIn("Заявка на франшизу", text)
        self.assertIn("Иван", text)
        self.assertIn("+79001234567", text)
        self.assertIn("Псков", text)

    async def test_city_and_comment_are_optional(self) -> None:
        notify = AsyncMock(return_value=1)
        await self._submit(notify, city="   ", comment=None)

        text = notify.await_args.args[0]
        self.assertIn("+79001234567", text)
        self.assertNotIn("🏙", text)
        self.assertNotIn("💬", text)

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
                franchise_leads._recent_by_ip.clear()
                franchise_leads._recent_global.clear()
                with self.assertRaises(HTTPException) as ctx:
                    await self._submit(notify, phone=bad)
                self.assertEqual(ctx.exception.status_code, 400)
                self.assertEqual(ctx.exception.detail, "INVALID_PHONE")
        notify.assert_not_awaited()

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
        for _ in range(franchise_leads._PER_IP_LIMIT):
            await self._submit(notify)

        with self.assertRaises(HTTPException) as ctx:
            await self._submit(notify)
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail, "TOO_MANY_REQUESTS")

        # Другой IP лимитом соседа не задет.
        with patch.object(franchise_leads, "notify_admins", notify):
            await create_franchise_lead(
                _request(forwarded="198.51.100.7"),
                FranchiseLeadPayload(name="Пётр", phone="+79007654321"),
            )
        self.assertEqual(notify.await_count, franchise_leads._PER_IP_LIMIT + 1)

    async def test_global_rate_limit(self) -> None:
        notify = AsyncMock(return_value=1)
        with patch.object(franchise_leads, "notify_admins", notify):
            for index in range(franchise_leads._GLOBAL_LIMIT):
                await create_franchise_lead(
                    _request(forwarded=f"198.51.100.{index}"),
                    FranchiseLeadPayload(name="Иван", phone="+79001234567"),
                )

            with self.assertRaises(HTTPException) as ctx:
                await create_franchise_lead(
                    _request(forwarded="198.51.100.200"),
                    FranchiseLeadPayload(name="Иван", phone="+79001234567"),
                )
        self.assertEqual(ctx.exception.status_code, 429)

    async def test_undelivered_lead_still_answers_ok(self) -> None:
        notify = AsyncMock(return_value=0)
        result = await self._submit(notify)
        self.assertEqual(result, {"data": {"delivered": 0}})


if __name__ == "__main__":
    unittest.main()
