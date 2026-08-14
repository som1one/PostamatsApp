"""Юнит-тесты для backend/utils/max_bot.py.

Проверяем, что:

- Без токена / получателей уведомление просто не идёт (нет HTTP-запросов).
- На каждого адресата уходит ровно один POST /messages c адресом в query
  (``chat_id`` либо ``user_id``), токеном в заголовке и inline-кнопкой
  внутри ``attachments``.
- Если MAX не принял HTML-разметку (400), тот же текст уезжает плоским.
- Сетевые ошибки и прочие не-2xx не пробрасываются наружу — клиентский
  запрос не должен падать из-за мессенджера.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from backend.core.settings import settings
from backend.utils.max_bot import notify_admins, parse_recipient, to_plain_text

_BASE_URL = "https://max.test"


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = '{"message":{}}') -> None:
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    """Контекст-менеджер, имитирующий httpx.AsyncClient.

    Ответы отдаются по очереди: последний повторяется, пока запросы не
    кончатся. Это нужно тесту про фолбэк «400 → повтор плоским текстом».
    """

    def __init__(
        self,
        calls: list[dict],
        responses: list[_FakeResponse] | _FakeResponse | Exception,
    ) -> None:
        self._calls = calls
        if isinstance(responses, (list, tuple)):
            self._responses = list(responses)
        else:
            self._responses = [responses]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url: str, **kwargs):
        self._calls.append({"url": url, **kwargs})
        response = (
            self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        )
        if isinstance(response, Exception):
            raise response
        return response


class ParseRecipientTests(unittest.TestCase):
    def test_bare_number_is_chat(self) -> None:
        self.assertEqual(parse_recipient("123"), ("chat_id", 123))

    def test_prefixes(self) -> None:
        self.assertEqual(parse_recipient("user:42"), ("user_id", 42))
        self.assertEqual(parse_recipient("chat:42"), ("chat_id", 42))

    def test_garbage_is_none(self) -> None:
        self.assertIsNone(parse_recipient("не число"))
        self.assertIsNone(parse_recipient("group:1"))
        self.assertIsNone(parse_recipient(""))


class PlainTextTests(unittest.TestCase):
    def test_strips_tags_and_unescapes(self) -> None:
        self.assertEqual(
            to_plain_text("<b>Заявка</b>\nИванов &amp; Ко"),
            "Заявка\nИванов & Ко",
        )


class MaxNotifyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_token = settings.MAX_ADMIN_BOT_TOKEN
        self._old_chats = list(settings.MAX_ADMIN_CHAT_IDS)
        self._old_base = settings.MAX_API_BASE_URL
        settings.MAX_API_BASE_URL = _BASE_URL

    def tearDown(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = self._old_token
        settings.MAX_ADMIN_CHAT_IDS = self._old_chats
        settings.MAX_API_BASE_URL = self._old_base

    async def test_no_token_skips_silently(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = None

        def factory(*args, **kwargs):  # pragma: no cover - guard
            raise AssertionError("HTTP client must not be instantiated without token")

        with patch("backend.utils.max_bot.httpx.AsyncClient", factory):
            delivered = await notify_admins("test", recipients=[("chat_id", 1)])

        self.assertEqual(delivered, 0)

    async def test_no_recipients_skips_silently(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = "max-token"

        def factory(*args, **kwargs):  # pragma: no cover - guard
            raise AssertionError("HTTP client must not be instantiated without chats")

        with patch("backend.utils.max_bot.httpx.AsyncClient", factory):
            delivered = await notify_admins("test", recipients=[])

        self.assertEqual(delivered, 0)

    async def test_sends_one_message_per_recipient_with_button(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = "max-token"
        calls: list[dict] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(calls, _FakeResponse(200))

        with patch("backend.utils.max_bot.httpx.AsyncClient", factory):
            delivered = await notify_admins(
                "<b>Заявка</b>",
                recipients=[("chat_id", 100), ("user_id", 200)],
                buttons=[("Открыть", "https://example.com/admin/")],
            )

        self.assertEqual(delivered, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual({call["url"] for call in calls}, {f"{_BASE_URL}/messages"})
        self.assertEqual(
            [call["params"] for call in calls],
            [{"chat_id": 100}, {"user_id": 200}],
        )

        for call in calls:
            self.assertEqual(call["headers"]["Authorization"], "max-token")
            self.assertEqual(call["json"]["text"], "<b>Заявка</b>")
            self.assertEqual(call["json"]["format"], "html")
            self.assertEqual(
                call["json"]["attachments"],
                [
                    {
                        "type": "inline_keyboard",
                        "payload": {
                            "buttons": [
                                [
                                    {
                                        "type": "link",
                                        "text": "Открыть",
                                        "url": "https://example.com/admin/",
                                    }
                                ]
                            ]
                        },
                    }
                ],
            )

    async def test_html_rejected_falls_back_to_plain_text(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = "max-token"
        calls: list[dict] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(
                calls, [_FakeResponse(400, "bad format"), _FakeResponse(200)]
            )

        with patch("backend.utils.max_bot.httpx.AsyncClient", factory):
            delivered = await notify_admins(
                "<b>Заявка</b> от Иванов &amp; Ко",
                recipients=[("chat_id", 100)],
            )

        self.assertEqual(delivered, 1)
        self.assertEqual(len(calls), 2)
        # Повтор — тот же адресат, но без разметки.
        self.assertNotIn("format", calls[1]["json"])
        self.assertEqual(calls[1]["json"]["text"], "Заявка от Иванов & Ко")

    async def test_request_error_is_swallowed(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = "max-token"
        calls: list[dict] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(calls, httpx.RequestError("boom"))

        with patch("backend.utils.max_bot.httpx.AsyncClient", factory):
            delivered = await notify_admins("hello", recipients=[("chat_id", 100)])

        self.assertEqual(delivered, 0)
        self.assertEqual(len(calls), 1)

    async def test_non_2xx_is_swallowed_without_retry(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = "max-token"
        calls: list[dict] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(calls, _FakeResponse(403, "forbidden"))

        with patch("backend.utils.max_bot.httpx.AsyncClient", factory):
            delivered = await notify_admins("hello", recipients=[("chat_id", 100)])

        self.assertEqual(delivered, 0)
        # 403 — не про разметку, повторять плоским текстом бессмысленно.
        self.assertEqual(len(calls), 1)

    async def test_csv_fallback_is_used_when_db_is_empty(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = "max-token"
        settings.MAX_ADMIN_CHAT_IDS = ["777", "user:888", "мусор"]
        calls: list[dict] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(calls, _FakeResponse(200))

        async def empty_db(*_args, **_kwargs):
            return []

        with patch("backend.utils.max_bot.httpx.AsyncClient", factory), patch(
            "backend.utils.max_admin_subscribers.get_active_recipients",
            side_effect=empty_db,
        ):
            delivered = await notify_admins("hello")

        self.assertEqual(delivered, 2)
        self.assertEqual(
            [call["params"] for call in calls],
            [{"chat_id": 777}, {"user_id": 888}],
        )


if __name__ == "__main__":
    unittest.main()
