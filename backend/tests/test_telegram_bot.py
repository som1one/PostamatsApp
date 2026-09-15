"""Юнит-тесты для backend/utils/telegram_bot.py.

Проверяем, что:

- Без токена / чатов уведомление просто не идёт (нет HTTP-запросов).
- При наличии конфигурации шлётся ровно один POST на каждый chat_id, c
  валидным JSON-телом (parse_mode HTML, inline-кнопка с URL).
- Сетевые ошибки и не-2xx ответы не пробрасываются наружу — клиентский
  запрос не должен падать из-за телеги.
- Фото: одно уходит ``sendPhoto`` с подписью и кнопками, несколько —
  ``sendMediaGroup`` и следом ``sendMessage`` с кнопками; байты грузятся
  по чатам по очереди, пока какой-нибудь их не примет, остальные (и те,
  у кого не вышло раньше) получают ``file_id``; недоступные чаты попытку
  не тратят, а после двух сбоев не по вине чата байты больше не грузятся
  и остальные получают текст; отвергнутое фото повторяется документом;
  сбой фото не мешает тексту, а таймаут после отправки не порождает дубль.
"""

from __future__ import annotations

import json
import unittest
from email.parser import BytesParser
from email.policy import default as email_policy
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx

from backend.core.settings import settings
from backend.utils.telegram_bot import TELEGRAM_CAPTION_LIMIT, notify_admins

_RealAsyncClient = httpx.AsyncClient

_API = "https://api.telegram.org/bot111:secret"


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
            await notify_admins("test", chat_ids=["123"])

        self.assertEqual(calls, [])

    async def test_no_chats_skips_silently(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "abc:xyz"
        settings.TELEGRAM_ADMIN_CHAT_IDS = []

        def factory(*args, **kwargs):  # pragma: no cover - guard
            raise AssertionError("HTTP client must not be instantiated without chats")

        with patch("backend.utils.telegram_bot.httpx.AsyncClient", factory):
            await notify_admins("test", chat_ids=[])

    async def test_sends_one_message_per_chat_id_with_button(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "111:secret"
        settings.TELEGRAM_ADMIN_CHAT_IDS = ["100", "200"]

        calls: list[tuple[str, dict]] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(calls, _FakeResponse(200))

        with patch("backend.utils.telegram_bot.httpx.AsyncClient", factory):
            await notify_admins(
                "<b>Заявка</b>",
                chat_ids=["100", "200"],
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
            await notify_admins("hello", chat_ids=["100"])

        # Один вызов был, но ошибка проглочена.
        self.assertEqual(len(calls), 1)

    async def test_non_2xx_is_swallowed(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "111:secret"
        settings.TELEGRAM_ADMIN_CHAT_IDS = ["100"]

        calls: list[tuple[str, dict]] = []

        def factory(*args, **kwargs):
            return _FakeAsyncClient(calls, _FakeResponse(403, "forbidden"))

        with patch("backend.utils.telegram_bot.httpx.AsyncClient", factory):
            await notify_admins("hello", chat_ids=["100"])

        self.assertEqual(len(calls), 1)

    async def test_text_only_keeps_default_timeout(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "111:secret"
        settings.TELEGRAM_API_TIMEOUT_SECONDS = 10

        calls: list[tuple[str, dict]] = []
        timeouts: list[object] = []

        def factory(*args, **kwargs):
            timeouts.append(kwargs.get("timeout"))
            return _FakeAsyncClient(calls, _FakeResponse(200))

        with patch("backend.utils.telegram_bot.httpx.AsyncClient", factory):
            delivered = await notify_admins("hello", chat_ids=["100"], photos=())

        self.assertEqual(delivered, 1)
        self.assertEqual(timeouts, [10])
        self.assertEqual([url for url, _ in calls], [f"{_API}/sendMessage"])


# --- Фото -----------------------------------------------------------------


def _photo_message(file_id: str) -> dict:
    return {
        "message_id": 1,
        "photo": [
            {"file_id": f"{file_id}-thumb", "width": 90},
            {"file_id": file_id, "width": 1280},
        ],
    }


def _document_message(file_id: str) -> dict:
    return {"message_id": 1, "document": {"file_id": file_id, "file_name": "x.jpg"}}


class _TelegramApi:
    """Настоящий httpx.AsyncClient поверх MockTransport.

    Запоминает каждый запрос целиком, чтобы тест мог разобрать multipart и
    убедиться, какие байты и поля реально ушли. Ответы по методам задаются
    функциями ``(request, form) -> httpx.Response``.
    """

    def __init__(self, **handlers) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.timeouts: list[object] = []
        self._handlers = handlers
        self._uploads = 0

    def factory(self, *args, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))
        return _RealAsyncClient(
            transport=httpx.MockTransport(self._handle), timeout=kwargs.get("timeout")
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        form = _parse_form(request)
        self.requests.append((method, form))
        handler = self._handlers.get(method)
        if handler is not None:
            return handler(request, form)
        return self._default(method, form)

    def _default(self, method: str, form: dict) -> httpx.Response:
        if method == "sendPhoto":
            self._uploads += 1
            return httpx.Response(
                200, json={"ok": True, "result": _photo_message(f"file-{self._uploads}")}
            )
        if method == "sendDocument":
            self._uploads += 1
            return httpx.Response(
                200, json={"ok": True, "result": _document_message(f"doc-{self._uploads}")}
            )
        if method == "sendMediaGroup":
            media = json.loads(form["fields"]["media"])
            build = _document_message if media[0]["type"] == "document" else _photo_message
            prefix = "doc-group" if media[0]["type"] == "document" else "group"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [build(f"{prefix}-{index}") for index in range(len(media))],
                },
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})

    def of(self, method: str) -> list[dict]:
        return [form for name, form in self.requests if name == method]

    def calls(self) -> list[tuple[str, str]]:
        """(метод, chat_id) в порядке запросов."""

        result = []
        for name, form in self.requests:
            chat = form["fields"].get("chat_id") or (form["json"] or {}).get("chat_id")
            result.append((name, chat))
        return result


def _parse_form(request: httpx.Request) -> dict:
    """Тело запроса: ``{"fields": {...}, "files": {...}, "json": ...}``."""

    body = request.read()
    content_type = request.headers.get("content-type", "")
    result: dict = {"fields": {}, "files": {}, "json": None, "content_type": content_type}
    if content_type.startswith("multipart/form-data"):
        message = BytesParser(policy=email_policy).parsebytes(
            b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
        )
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            payload = part.get_payload(decode=True)
            filename = part.get_filename()
            if filename is None:
                result["fields"][name] = payload.decode("utf-8")
            else:
                result["files"][name] = (filename, payload, part.get_content_type())
    elif content_type.startswith("application/x-www-form-urlencoded"):
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        result["fields"] = {key: values[0] for key, values in parsed.items()}
    elif content_type.startswith("application/json"):
        result["json"] = json.loads(body)
    return result


_BUTTONS = [("Проверить возврат", "https://admin.test/?section=rentals&rental=1")]
_MARKUP = {
    "inline_keyboard": [
        [{"text": "Проверить возврат", "url": "https://admin.test/?section=rentals&rental=1"}]
    ]
}


def _photo(index: int) -> tuple[str, bytes, str]:
    return (f"return-{index}.jpg", f"jpeg-bytes-{index}".encode(), "image/jpeg")


def _error(status: int = 400, text: str = "Bad Request: IMAGE_PROCESS_FAILED"):
    def handler(request, form):
        return httpx.Response(status, json={"ok": False, "description": text})

    return handler


def _per_chat(api_ref: list, errors: dict[str, object], method: str):
    """Ответ по chat_id: ``httpx.Response``, исключение или ответ по умолчанию."""

    def handler(request, form):
        chat = form["fields"].get("chat_id") or (form["json"] or {}).get("chat_id")
        error = errors.get(chat)
        if isinstance(error, type) and issubclass(error, Exception):
            raise error("boom", request=request)
        if isinstance(error, httpx.Response):
            return error
        return api_ref[0]._default(method, form)

    return handler


def _forbidden() -> httpx.Response:
    return httpx.Response(
        403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}
    )


class TelegramPhotoNotifyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_token = settings.TELEGRAM_ADMIN_BOT_TOKEN
        self._old_timeout = settings.TELEGRAM_API_TIMEOUT_SECONDS
        settings.TELEGRAM_ADMIN_BOT_TOKEN = "111:secret"
        settings.TELEGRAM_API_TIMEOUT_SECONDS = 10

    def tearDown(self) -> None:
        settings.TELEGRAM_ADMIN_BOT_TOKEN = self._old_token
        settings.TELEGRAM_API_TIMEOUT_SECONDS = self._old_timeout

    async def _notify(self, api: _TelegramApi, text: str, **kwargs) -> int:
        with patch("backend.utils.telegram_bot.httpx.AsyncClient", api.factory):
            return await notify_admins(text, buttons=_BUTTONS, **kwargs)

    def _api_with_chat_errors(self, **per_method: dict[str, object]) -> _TelegramApi:
        api_ref: list[_TelegramApi] = []
        api = _TelegramApi(
            **{
                method: _per_chat(api_ref, errors, method)
                for method, errors in per_method.items()
            }
        )
        api_ref.append(api)
        return api

    async def test_single_photo_goes_as_send_photo_with_caption_and_buttons(self) -> None:
        api = _TelegramApi()

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100"], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 1)
        self.assertEqual([name for name, _ in api.requests], ["sendPhoto"])
        form = api.requests[0][1]
        self.assertTrue(form["content_type"].startswith("multipart/form-data"))
        self.assertEqual(form["fields"]["chat_id"], "100")
        self.assertEqual(form["fields"]["caption"], "<b>Возврат</b>")
        self.assertEqual(form["fields"]["parse_mode"], "HTML")
        self.assertEqual(json.loads(form["fields"]["reply_markup"]), _MARKUP)
        self.assertEqual(
            form["files"]["photo"], ("return-1.jpg", b"jpeg-bytes-1", "image/jpeg")
        )
        # Загрузка фото дольше обычного сообщения — таймаут не меньше 30 с.
        self.assertGreaterEqual(api.timeouts[0], 30)

    async def test_several_photos_go_as_media_group_then_message_with_buttons(self) -> None:
        api = _TelegramApi()

        delivered = await self._notify(
            api,
            "<b>Возврат</b>",
            chat_ids=["100"],
            photos=[_photo(1), _photo(2), _photo(3)],
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(
            [name for name, _ in api.requests], ["sendMediaGroup", "sendMessage"]
        )
        group = api.requests[0][1]
        self.assertEqual(group["fields"]["chat_id"], "100")
        self.assertEqual(
            json.loads(group["fields"]["media"]),
            [
                {"type": "photo", "media": "attach://p0"},
                {"type": "photo", "media": "attach://p1"},
                {"type": "photo", "media": "attach://p2"},
            ],
        )
        self.assertNotIn("caption", group["fields"])
        self.assertEqual(
            {name: content for name, (_, content, _) in group["files"].items()},
            {"p0": b"jpeg-bytes-1", "p1": b"jpeg-bytes-2", "p2": b"jpeg-bytes-3"},
        )

        message = api.requests[1][1]["json"]
        self.assertEqual(message["chat_id"], "100")
        self.assertEqual(message["text"], "<b>Возврат</b>")
        self.assertEqual(message["parse_mode"], "HTML")
        self.assertEqual(message["reply_markup"], _MARKUP)

    async def test_second_chat_reuses_file_id_without_uploading_bytes(self) -> None:
        api = _TelegramApi()

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100", "200"], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 2)
        first, second = api.of("sendPhoto")
        self.assertEqual(first["fields"]["chat_id"], "100")
        self.assertIn("photo", first["files"])

        self.assertEqual(second["fields"]["chat_id"], "200")
        self.assertEqual(second["files"], {})
        self.assertNotIn(b"jpeg-bytes-1", json.dumps(second["fields"]).encode())
        # Берём самый крупный размер из ответа первого чата.
        self.assertEqual(second["fields"]["photo"], "file-1")
        self.assertEqual(second["fields"]["caption"], "<b>Возврат</b>")
        self.assertEqual(json.loads(second["fields"]["reply_markup"]), _MARKUP)

    async def test_second_chat_reuses_media_group_file_ids(self) -> None:
        api = _TelegramApi()

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100", "200"], photos=[_photo(1), _photo(2)]
        )

        self.assertEqual(delivered, 2)
        first, second = api.of("sendMediaGroup")
        self.assertEqual(len(first["files"]), 2)
        self.assertEqual(second["fields"]["chat_id"], "200")
        self.assertEqual(second["files"], {})
        self.assertEqual(
            json.loads(second["fields"]["media"]),
            [
                {"type": "photo", "media": "group-0"},
                {"type": "photo", "media": "group-1"},
            ],
        )
        self.assertEqual(
            [form["json"]["chat_id"] for form in api.of("sendMessage")], ["100", "200"]
        )

    async def test_photo_failure_falls_back_to_send_message(self) -> None:
        api = _TelegramApi(sendPhoto=_error(500, "Internal Server Error"))

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100"], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 1)
        # 500 — не про сами фото: документом не повторяем, сразу текст.
        self.assertEqual([name for name, _ in api.requests], ["sendPhoto", "sendMessage"])
        message = api.requests[1][1]["json"]
        self.assertEqual(message["text"], "<b>Возврат</b>")
        self.assertEqual(message["reply_markup"], _MARKUP)

    async def test_photo_network_error_falls_back_to_send_message(self) -> None:
        def broken(request, form):
            raise httpx.ConnectError("boom", request=request)

        api = _TelegramApi(sendMediaGroup=broken)

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100"], photos=[_photo(1), _photo(2)]
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(
            [name for name, _ in api.requests], ["sendMediaGroup", "sendMessage"]
        )

    async def test_unreachable_first_chats_do_not_cost_others_the_photos(self) -> None:
        # Два первых подписчика заблокировали бота: раньше после двух
        # провалов подряд остальные чаты получали только текст.
        blocked = {"1": _forbidden(), "2": _forbidden()}
        api = self._api_with_chat_errors(sendPhoto=blocked, sendMessage=blocked)

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["1", "2", "3", "4", "5"], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 3)
        uploads = [form for form in api.of("sendPhoto") if form["files"]]
        self.assertEqual([form["fields"]["chat_id"] for form in uploads], ["1", "2", "3"])
        by_file_id = {
            form["fields"]["chat_id"]: form["fields"]["photo"]
            for form in api.of("sendPhoto")
            if not form["files"]
        }
        # Работающие операторы получили фото, недоступные чаты — попытку по file_id.
        self.assertEqual(
            by_file_id, {"1": "file-1", "2": "file-1", "4": "file-1", "5": "file-1"}
        )
        # Текст-фолбэк — только тем, у кого фото не ушло и по file_id.
        self.assertEqual(
            sorted(form["json"]["chat_id"] for form in api.of("sendMessage")), ["1", "2"]
        )

    async def test_failed_chat_is_retried_with_file_id_instead_of_text(self) -> None:
        api_ref: list[_TelegramApi] = []

        def flaky_first_upload(request, form):
            if form["fields"].get("chat_id") == "100" and form["files"]:
                return httpx.Response(500, json={"ok": False, "description": "oops"})
            return api_ref[0]._default("sendPhoto", form)

        api = _TelegramApi(sendPhoto=flaky_first_upload)
        api_ref.append(api)

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100", "200"], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 2)
        self.assertEqual(
            api.calls(),
            [("sendPhoto", "100"), ("sendPhoto", "200"), ("sendPhoto", "100")],
        )
        retry = api.of("sendPhoto")[2]
        self.assertEqual(retry["files"], {})
        self.assertEqual(retry["fields"]["photo"], "file-1")
        self.assertEqual(retry["fields"]["caption"], "<b>Возврат</b>")
        # Фото с подписью дошло — отдельный текст был бы дублем.
        self.assertEqual(api.of("sendMessage"), [])

    async def test_server_errors_stop_uploads_after_two_chats(self) -> None:
        api = _TelegramApi(sendPhoto=_error(500, "Internal Server Error"))

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100", "200", "300"], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 3)
        # Две загрузки упали не по вине чата — третьему байты уже не грузим.
        self.assertEqual(
            [form["fields"]["chat_id"] for form in api.of("sendPhoto")], ["100", "200"]
        )
        self.assertTrue(all(form["files"] for form in api.of("sendPhoto")))
        self.assertEqual(
            sorted(form["json"]["chat_id"] for form in api.of("sendMessage")),
            ["100", "200", "300"],
        )

    async def test_write_timeouts_everywhere_stop_uploads_and_text_reaches_the_rest(
        self,
    ) -> None:
        chats = ["1", "2", "3", "4", "5"]
        api = self._api_with_chat_errors(
            sendPhoto={chat: httpx.WriteTimeout for chat in chats}
        )

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=chats, photos=[_photo(1)]
        )

        # Не пять загрузок по 30 с подряд, а две, и потом сразу текст.
        self.assertEqual(api.calls()[:2], [("sendPhoto", "1"), ("sendPhoto", "2")])
        self.assertEqual(len(api.of("sendPhoto")), 2)
        self.assertEqual(api.of("sendDocument"), [])
        # Чаты 1 и 2 могли получить фото с подписью — им текст не дублируем;
        # до чатов 3–5 фото не доходило, текст уходит им.
        messages = api.of("sendMessage")
        self.assertEqual(
            sorted(form["json"]["chat_id"] for form in messages), ["3", "4", "5"]
        )
        for form in messages:
            self.assertEqual(form["json"]["text"], "<b>Возврат</b>")
            self.assertEqual(form["json"]["reply_markup"], _MARKUP)
        self.assertEqual(delivered, 3)

    async def test_album_read_timeouts_send_each_chat_the_text_once(self) -> None:
        chats = ["1", "2", "3", "4"]
        api = self._api_with_chat_errors(
            sendMediaGroup={chat: httpx.ReadTimeout for chat in chats}
        )

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=chats, photos=[_photo(1), _photo(2)]
        )

        self.assertEqual(
            [form["fields"]["chat_id"] for form in api.of("sendMediaGroup")], ["1", "2"]
        )
        # У альбома текст отдельный: чаты 1–2 получили его сразу, 3–4 — после
        # остановки загрузок, и никто — дважды.
        self.assertEqual(
            sorted(form["json"]["chat_id"] for form in api.of("sendMessage")), chats
        )
        self.assertEqual(delivered, 4)

    async def test_rate_limit_everywhere_stops_uploads_then_sends_text(self) -> None:
        chats = ["1", "2", "3", "4", "5"]
        api = _TelegramApi(sendPhoto=_error(429, "Too Many Requests: retry after 5"))

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=chats, photos=[_photo(1)]
        )

        self.assertEqual(delivered, 5)
        uploads = api.of("sendPhoto")
        self.assertEqual([form["fields"]["chat_id"] for form in uploads], ["1", "2"])
        self.assertTrue(all(form["files"] for form in uploads))
        # 429 — не про сами фото: документом не повторяем.
        self.assertEqual(api.of("sendDocument"), [])
        self.assertEqual(
            sorted(form["json"]["chat_id"] for form in api.of("sendMessage")), chats
        )

    async def test_rejected_photo_and_document_stop_uploads_after_two_chats(self) -> None:
        chats = ["1", "2", "3", "4", "5"]
        api = _TelegramApi(
            sendPhoto=_error(400, "Bad Request: IMAGE_PROCESS_FAILED"),
            sendDocument=_error(400, "Bad Request: file must be non-empty"),
        )

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=chats, photos=[_photo(1)]
        )

        self.assertEqual(delivered, 5)
        # Фото и документ — одна неудачная попытка чата; после двух таких стоп.
        self.assertEqual(
            api.calls()[:4],
            [
                ("sendPhoto", "1"),
                ("sendDocument", "1"),
                ("sendPhoto", "2"),
                ("sendDocument", "2"),
            ],
        )
        self.assertEqual(len(api.of("sendPhoto")), 2)
        self.assertEqual(len(api.of("sendDocument")), 2)
        self.assertEqual(
            sorted(form["json"]["chat_id"] for form in api.of("sendMessage")), chats
        )

    async def test_blocked_chats_do_not_count_toward_upload_limit(self) -> None:
        # 403, 403, «chat not found» и одна 5xx — лимит (две сбойные загрузки
        # не по вине чата) не исчерпан, пятый чат принимает байты.
        blocked = {
            "1": _forbidden(),
            "2": _forbidden(),
            "3": httpx.Response(
                400, json={"ok": False, "description": "Bad Request: chat not found"}
            ),
        }
        api_ref: list[_TelegramApi] = []

        def upload(request, form):
            chat = form["fields"]["chat_id"]
            if chat in blocked:
                return blocked[chat]
            if chat == "4" and form["files"]:
                return httpx.Response(500, json={"ok": False, "description": "oops"})
            return api_ref[0]._default("sendPhoto", form)

        api = _TelegramApi(
            sendPhoto=upload, sendMessage=_per_chat(api_ref, blocked, "sendMessage")
        )
        api_ref.append(api)

        delivered = await self._notify(
            api,
            "<b>Возврат</b>",
            chat_ids=["1", "2", "3", "4", "5", "6"],
            photos=[_photo(1)],
        )

        uploads = [form for form in api.of("sendPhoto") if form["files"]]
        self.assertEqual(
            [form["fields"]["chat_id"] for form in uploads], ["1", "2", "3", "4", "5"]
        )
        self.assertEqual(api.of("sendDocument"), [])
        by_file_id = {
            form["fields"]["chat_id"]: form["fields"]["photo"]
            for form in api.of("sendPhoto")
            if not form["files"]
        }
        self.assertEqual(
            by_file_id, {chat: "file-1" for chat in ("1", "2", "3", "4", "6")}
        )
        # Чат 4 упал на байтах, но фото по file_id дошло; 5 и 6 — тоже.
        self.assertEqual(delivered, 3)
        self.assertEqual(
            sorted(form["json"]["chat_id"] for form in api.of("sendMessage")),
            ["1", "2", "3"],
        )

    async def test_blocked_first_chat_passes_upload_to_next_chat(self) -> None:
        api = self._api_with_chat_errors(sendPhoto={"100": _forbidden()})

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100", "200", "300"], photos=[_photo(1)]
        )

        # Второй чат принял байты, третий — тот же file_id; первый попробовал
        # file_id и получил текстовый фолбэк.
        self.assertEqual(delivered, 3)
        uploads = api.of("sendPhoto")
        self.assertEqual(
            [form["fields"]["chat_id"] for form in uploads[:2]], ["100", "200"]
        )
        self.assertIn("photo", uploads[0]["files"])
        self.assertIn("photo", uploads[1]["files"])
        # 403 — проблема чата, а не фото: документом не повторяем.
        self.assertEqual(api.of("sendDocument"), [])
        reused = {form["fields"]["chat_id"]: form for form in uploads[2:]}
        self.assertEqual(set(reused), {"100", "300"})
        for form in reused.values():
            self.assertEqual(form["files"], {})
            self.assertEqual(form["fields"]["photo"], "file-1")
        self.assertEqual(
            [form["json"]["chat_id"] for form in api.of("sendMessage")], ["100"]
        )

    async def test_rejected_photo_is_retried_as_document(self) -> None:
        api = _TelegramApi(
            sendPhoto=_error(400, "Bad Request: PHOTO_INVALID_DIMENSIONS")
        )

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100", "200"], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 2)
        self.assertEqual(
            api.calls(),
            [("sendPhoto", "100"), ("sendDocument", "100"), ("sendDocument", "200")],
        )
        first, second = api.of("sendDocument")
        self.assertEqual(
            first["files"]["document"], ("return-1.jpg", b"jpeg-bytes-1", "image/jpeg")
        )
        self.assertEqual(first["fields"]["caption"], "<b>Возврат</b>")
        self.assertEqual(first["fields"]["parse_mode"], "HTML")
        self.assertEqual(json.loads(first["fields"]["reply_markup"]), _MARKUP)
        # Второй чат сразу получает документ по file_id, без байтов и без sendPhoto.
        self.assertEqual(second["files"], {})
        self.assertEqual(second["fields"]["document"], "doc-1")
        self.assertEqual(second["fields"]["caption"], "<b>Возврат</b>")
        self.assertEqual(api.of("sendMessage"), [])

    async def test_rejected_album_is_retried_as_document_album(self) -> None:
        def reject_photo_album(request, form):
            media = json.loads(form["fields"]["media"])
            if media[0]["type"] == "photo":
                return httpx.Response(
                    400, json={"ok": False, "description": "Bad Request: IMAGE_PROCESS_FAILED"}
                )
            return api._default("sendMediaGroup", form)

        api = _TelegramApi(sendMediaGroup=reject_photo_album)

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100", "200"], photos=[_photo(1), _photo(2)]
        )

        self.assertEqual(delivered, 2)
        groups = api.of("sendMediaGroup")
        self.assertEqual(len(groups), 3)
        self.assertEqual(
            json.loads(groups[1]["fields"]["media"]),
            [
                {"type": "document", "media": "attach://p0"},
                {"type": "document", "media": "attach://p1"},
            ],
        )
        self.assertEqual(len(groups[1]["files"]), 2)
        self.assertEqual(groups[2]["fields"]["chat_id"], "200")
        self.assertEqual(groups[2]["files"], {})
        self.assertEqual(
            json.loads(groups[2]["fields"]["media"]),
            [
                {"type": "document", "media": "doc-group-0"},
                {"type": "document", "media": "doc-group-1"},
            ],
        )
        self.assertEqual(
            [form["json"]["chat_id"] for form in api.of("sendMessage")], ["100", "200"]
        )

    async def test_rejected_document_falls_back_to_text(self) -> None:
        api = _TelegramApi(
            sendPhoto=_error(400, "Bad Request: PHOTO_SAVE_FILE_INVALID"),
            sendDocument=_error(400, "Bad Request: file must be non-empty"),
        )

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100"], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(
            [name for name, _ in api.requests], ["sendPhoto", "sendDocument", "sendMessage"]
        )

    async def test_missing_chat_is_not_retried_as_document(self) -> None:
        api = _TelegramApi(sendPhoto=_error(400, "Bad Request: chat not found"))

        await self._notify(api, "<b>Возврат</b>", chat_ids=["100"], photos=[_photo(1)])

        self.assertEqual([name for name, _ in api.requests], ["sendPhoto", "sendMessage"])

    async def test_read_timeout_after_photo_with_caption_sends_no_duplicate_text(self) -> None:
        api = self._api_with_chat_errors(sendPhoto={"100": httpx.ReadTimeout})

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100", "200"], photos=[_photo(1)]
        )

        # Первый чат, возможно, уже получил фото с подписью: ни текста, ни
        # повтора по file_id. Байты уходят следующему чату.
        self.assertEqual(delivered, 1)
        self.assertEqual(api.calls(), [("sendPhoto", "100"), ("sendPhoto", "200")])
        self.assertIn("photo", api.of("sendPhoto")[1]["files"])
        self.assertEqual(api.of("sendDocument"), [])

    async def test_write_timeout_is_treated_as_maybe_delivered(self) -> None:
        api = self._api_with_chat_errors(sendPhoto={"100": httpx.WriteTimeout})

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100"], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 0)
        self.assertEqual(api.calls(), [("sendPhoto", "100")])

    async def test_connect_timeout_still_falls_back_to_text(self) -> None:
        api = self._api_with_chat_errors(sendPhoto={"100": httpx.ConnectTimeout})

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100"], photos=[_photo(1)]
        )

        # Соединение не установилось — запрос точно не дошёл.
        self.assertEqual(delivered, 1)
        self.assertEqual(api.calls(), [("sendPhoto", "100"), ("sendMessage", "100")])

    async def test_album_timeout_still_sends_separate_text_once(self) -> None:
        api = self._api_with_chat_errors(sendMediaGroup={"100": httpx.ReadTimeout})

        delivered = await self._notify(
            api, "<b>Возврат</b>", chat_ids=["100"], photos=[_photo(1), _photo(2)]
        )

        # Текст у альбома отдельный — это не дубль, а обычное сообщение с кнопками.
        self.assertEqual(delivered, 1)
        self.assertEqual(api.calls(), [("sendMediaGroup", "100"), ("sendMessage", "100")])

    async def test_long_text_goes_as_separate_message_after_photo(self) -> None:
        api = _TelegramApi()
        text = "<b>Возврат</b>\n" + "а" * TELEGRAM_CAPTION_LIMIT

        delivered = await self._notify(api, text, chat_ids=["100"], photos=[_photo(1)])

        self.assertEqual(delivered, 1)
        self.assertEqual([name for name, _ in api.requests], ["sendPhoto", "sendMessage"])
        photo = api.requests[0][1]
        self.assertNotIn("caption", photo["fields"])
        self.assertNotIn("reply_markup", photo["fields"])
        message = api.requests[1][1]["json"]
        self.assertEqual(message["text"], text)
        self.assertEqual(message["reply_markup"], _MARKUP)

    async def test_long_text_is_not_repeated_after_failed_photo(self) -> None:
        api = _TelegramApi(sendPhoto=_error(500, "Internal Server Error"))
        text = "<b>Возврат</b>\n" + "а" * TELEGRAM_CAPTION_LIMIT

        delivered = await self._notify(api, text, chat_ids=["100"], photos=[_photo(1)])

        self.assertEqual(delivered, 1)
        self.assertEqual([name for name, _ in api.requests], ["sendPhoto", "sendMessage"])

    async def test_without_photos_uses_plain_send_message(self) -> None:
        api = _TelegramApi()

        delivered = await self._notify(api, "<b>Возврат</b>", chat_ids=["100", "200"])

        self.assertEqual(delivered, 2)
        self.assertEqual(
            [name for name, _ in api.requests], ["sendMessage", "sendMessage"]
        )
        self.assertEqual(api.timeouts, [10])
        for _, form in api.requests:
            self.assertEqual(form["json"]["reply_markup"], _MARKUP)
            self.assertTrue(form["json"]["disable_web_page_preview"])


if __name__ == "__main__":
    unittest.main()
