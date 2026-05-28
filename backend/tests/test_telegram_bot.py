"""Юнит-тесты для backend/utils/telegram_bot.py.

Проверяем, что:

- Без токена / чатов уведомление просто не идёт (нет HTTP-запросов).
- При наличии конфигурации шлётся ровно один POST на каждый chat_id, c
  валидным JSON-телом (parse_mode HTML, inline-кнопка с URL).
- Сетевые ошибки и не-2xx ответы не пробрасываются наружу — клиентский
  запрос не должен падать из-за телеги.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.core.settings import settings
from backend.utils.telegram_bot import notify_admins


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = '{"ok":true}') -> None:
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    """Контекст-менеджер, имитирующий httpx.AsyncClient.

    Сохраняет все вызовы post() в общий список, чтобы тесты могли их
    проинспектировать.
    """

    def __init__(self, calls: list[tuple[str, dict]], response: _FakeResponse | Exception):
        self._calls = calls
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url: str, json: dict | None = None, **_: object):
        self._calls.append((url, json or {}))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class TelegramNotifyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_token = settings.TELEGRAM_ADMIN_BOT_TOKEN
        self._old_chats = list(settings.TELEGRAM_ADMIN_CHAT_IDS)
        self._old_timeout = settings.TELEGRAM_API_TIMEOUT_SECONDS

    def tearDown(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = self._old_token
        settings.TELEGRAM_ADMIN_CHAT_IDS = self._old_chats
        settings.TELEGRAM_API_TIMEOUT_SECONDS = self._old_timeout

    async def test_no_token_skips_silently(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = None
        settings.TELEGRAM_ADMIN_CHAT_IDS = ["123"]

        calls: list[tuple[str, dict]] = []

        def factory(*args, **kwargs):  # pragma: no cover - guard
            raise AssertionError("HTTP client must not be instantiated when token is missing")

        with patch("backend.utils.telegram_bot.httpx.AsyncClient", factory):
            await notify_admins("test")

        self.assertEqual(calls, [])

    async def test_no_chats_skips_silently(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "abc:xyz"
        settings.TELEGRAM_ADMIN_CHAT_IDS = []

        def factory(*args, **kwargs):  # pragma: no cover - guard
            raise AssertionError("HTTP client must not be instantiated without chats")

        with patch("backend.utils.telegram_bot.httpx.AsyncClient", factory):
            await notify_admins("test")

    async def test_sends_one_message_per_chat_id_with_button(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "111:secret"
        settings.TELEGRAM_ADMIN_CHAT_IDS = ["100", "200"]

        calls: list[tuple[str, dict]] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(calls, _FakeResponse(200))

        with patch("backend.utils.telegram_bot.httpx.AsyncClient", factory):
            await notify_admins(
                "<b>Заявка</b>",
                buttons=[("Открыть", "https://example.com/admin/?section=verification")],
            )

        self.assertEqual(len(calls), 2)
        urls = {url for url, _ in calls}
        self.assertEqual(urls, {"https://api.telegram.org/bot111:secret/sendMessage"})

        chats_seen = {payload["chat_id"] for _, payload in calls}
        self.assertEqual(chats_seen, {"100", "200"})

        for _, payload in calls:
            self.assertEqual(payload["text"], "<b>Заявка</b>")
            self.assertEqual(payload["parse_mode"], "HTML")
            self.assertTrue(payload["disable_web_page_preview"])
            self.assertEqual(
                payload["reply_markup"],
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "Открыть",
                                "url": "https://example.com/admin/?section=verification",
                            }
                        ]
                    ]
                },
            )

    async def test_request_error_is_swallowed(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "111:secret"
        settings.TELEGRAM_ADMIN_CHAT_IDS = ["100"]

        calls: list[tuple[str, dict]] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(calls, httpx.RequestError("boom"))

        with patch("backend.utils.telegram_bot.httpx.AsyncClient", factory):
            # Должно не упасть.
            await notify_admins("hello")

        # Один вызов был, но ошибка проглочена.
        self.assertEqual(len(calls), 1)

    async def test_non_2xx_is_swallowed(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "111:secret"
        settings.TELEGRAM_ADMIN_CHAT_IDS = ["100"]

        calls: list[tuple[str, dict]] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(calls, _FakeResponse(403, "forbidden"))

        with patch("backend.utils.telegram_bot.httpx.AsyncClient", factory):
            await notify_admins("hello")

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
