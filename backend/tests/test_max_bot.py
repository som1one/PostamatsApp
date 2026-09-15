"""Юнит-тесты для backend/utils/max_bot.py.

Проверяем, что:

- Без токена / получателей уведомление просто не идёт (нет HTTP-запросов).
- На каждого адресата уходит ровно один POST /messages c адресом в query
  (``chat_id`` либо ``user_id``), токеном в заголовке и inline-кнопкой
  внутри ``attachments``.
- Если MAX не принял HTML-разметку (400), тот же текст уезжает плоским.
- Сетевые ошибки и прочие не-2xx не пробрасываются наружу — клиентский
  запрос не должен падать из-за мессенджера.
- Фото загружаются один раз (слот → сервер загрузки → токен) и уходят
  вложениями перед клавиатурой; не принятая картинка грузится файлом;
  после двух незагрузившихся фото остальные не грузятся;
  ``attachment.not.ready`` повторяется с паузами, а любой сбой фото
  оставляет адресату обычный текст — кроме таймаута после отправки, где
  текст стал бы дублем.
"""

from __future__ import annotations

import json
import unittest
from email.parser import BytesParser
from email.policy import default as email_policy
from unittest.mock import AsyncMock, patch

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


# --- Фото -----------------------------------------------------------------

_RealAsyncClient = httpx.AsyncClient

_UPLOAD_HOST = "https://iu.max.test"

_KEYBOARD = {
    "type": "inline_keyboard",
    "payload": {
        "buttons": [
            [
                {
                    "type": "link",
                    "text": "Проверить возврат",
                    "url": "https://admin.test/?section=rentals&rental=1",
                }
            ]
        ]
    },
}

_NOT_READY = {
    "code": "attachment.not.ready",
    "message": "Key: errors.process.attachment.file.not.processed",
}


def _photo(index: int) -> tuple[str, bytes, str]:
    return (f"return-{index}.jpg", f"jpeg-bytes-{index}".encode(), "image/jpeg")


class _MaxApi:
    """Настоящий httpx.AsyncClient поверх MockTransport.

    Эмулирует три шага MAX: слот загрузки на API-хосте, сервер загрузки,
    отправку сообщения. Ответы ``/messages`` можно задать очередью.
    """

    def __init__(
        self,
        *,
        slot_status: int = 200,
        slot_payload=None,
        upload_status=200,
        upload_payload=None,
        messages: list[httpx.Response | type[Exception]] | None = None,
    ) -> None:
        """``upload_status`` — число или ``(тип загрузки, имя файла) -> статус``
        (статус может быть и классом исключения); ``slot_payload`` —
        ``(тип, номер слота) -> dict``; в очереди ``messages`` можно
        класть классы исключений httpx."""

        self.slots: list[httpx.Request] = []
        self.uploads: list[dict] = []
        self.messages: list[dict] = []
        self.timeouts: list[object] = []
        self._slot_status = slot_status
        self._slot_payload = slot_payload
        self._upload_status = upload_status
        self._upload_payload = upload_payload
        self._message_responses = list(messages or [])

    def factory(self, *args, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))
        return _RealAsyncClient(
            transport=httpx.MockTransport(self._handle), timeout=kwargs.get("timeout")
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(f"{_BASE_URL}/uploads"):
            self.slots.append(request)
            if self._slot_status >= 400:
                return httpx.Response(self._slot_status, text="upload slot error")
            index = len(self.slots)
            upload_type = request.url.params["type"]
            payload = (
                self._slot_payload(upload_type, index)
                if self._slot_payload is not None
                else {"url": f"{_UPLOAD_HOST}/upload.do?type={upload_type}&slot={index}"}
            )
            return httpx.Response(200, json=payload)

        if url.startswith(_UPLOAD_HOST):
            body = request.read()
            content_type = request.headers["content-type"]
            message = BytesParser(policy=email_policy).parsebytes(
                b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
            )
            parts = {
                part.get_param("name", header="content-disposition"): (
                    part.get_filename(),
                    part.get_payload(decode=True),
                    part.get_content_type(),
                )
                for part in message.iter_parts()
            }
            upload_type = request.url.params.get("type")
            self.uploads.append(
                {
                    "headers": dict(request.headers),
                    "content_type": content_type,
                    "parts": parts,
                    "type": upload_type,
                }
            )
            status = self._upload_status
            if callable(status) and not isinstance(status, type):
                status = status(upload_type, parts["data"][0])
            if isinstance(status, type) and issubclass(status, Exception):
                raise status("boom", request=request)
            if status >= 400:
                return httpx.Response(status, text="upload failed")
            index = len(self.uploads)
            payload = (
                self._upload_payload(index)
                if self._upload_payload is not None
                else {"token": f"token-{index}"}
            )
            if payload is None:
                return httpx.Response(200, text="OK")
            return httpx.Response(200, json=payload)

        if url.startswith(f"{_BASE_URL}/messages"):
            self.messages.append(
                {
                    "params": dict(request.url.params),
                    "headers": dict(request.headers),
                    "json": json.loads(request.read()),
                }
            )
            if self._message_responses:
                response = self._message_responses.pop(0)
                if isinstance(response, type) and issubclass(response, Exception):
                    raise response("boom", request=request)
                return response
            return httpx.Response(200, json={"message": {}})

        raise AssertionError(f"unexpected request {request.method} {url}")


class MaxPhotoNotifyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_token = settings.MAX_ADMIN_BOT_TOKEN
        self._old_base = settings.MAX_API_BASE_URL
        self._old_timeout = settings.MAX_API_TIMEOUT_SECONDS
        settings.MAX_ADMIN_BOT_TOKEN = "max-token"
        settings.MAX_API_BASE_URL = _BASE_URL
        settings.MAX_API_TIMEOUT_SECONDS = 10

    def tearDown(self) -> None:
        settings.MAX_ADMIN_BOT_TOKEN = self._old_token
        settings.MAX_API_BASE_URL = self._old_base
        settings.MAX_API_TIMEOUT_SECONDS = self._old_timeout

    async def _notify(self, api: _MaxApi, **kwargs) -> tuple[int, AsyncMock]:
        sleep = AsyncMock()
        with patch("backend.utils.max_bot.httpx.AsyncClient", api.factory), patch(
            "backend.utils.max_bot.asyncio.sleep", sleep
        ):
            delivered = await notify_admins(
                "<b>Возврат</b>",
                buttons=[
                    ("Проверить возврат", "https://admin.test/?section=rentals&rental=1")
                ],
                **kwargs,
            )
        return delivered, sleep

    async def test_uploads_once_and_sends_image_attachments_with_keyboard(self) -> None:
        api = _MaxApi()

        delivered, _ = await self._notify(
            api,
            recipients=[("chat_id", 100), ("user_id", 200)],
            photos=[_photo(1), _photo(2)],
        )

        self.assertEqual(delivered, 2)
        # Каждое фото загружено ровно один раз, независимо от числа адресатов.
        self.assertEqual(len(api.slots), 2)
        for slot in api.slots:
            self.assertEqual(slot.method, "POST")
            self.assertEqual(slot.url.params["type"], "image")
            self.assertEqual(slot.headers["authorization"], "max-token")
            self.assertNotIn("application/json", slot.headers.get("content-type", ""))

        self.assertEqual(len(api.uploads), 2)
        for index, upload in enumerate(api.uploads, start=1):
            self.assertTrue(upload["content_type"].startswith("multipart/form-data"))
            # Токен бота на сервер загрузки не уходит.
            self.assertNotIn("authorization", upload["headers"])
            self.assertEqual(
                upload["parts"]["data"],
                (f"return-{index}.jpg", f"jpeg-bytes-{index}".encode(), "image/jpeg"),
            )

        self.assertEqual(
            [message["params"] for message in api.messages],
            [{"chat_id": "100"}, {"user_id": "200"}],
        )
        for message in api.messages:
            self.assertEqual(message["headers"]["authorization"], "max-token")
            self.assertEqual(message["json"]["text"], "<b>Возврат</b>")
            self.assertEqual(message["json"]["format"], "html")
            self.assertEqual(
                message["json"]["attachments"],
                [
                    {"type": "image", "payload": {"token": "token-1"}},
                    {"type": "image", "payload": {"token": "token-2"}},
                    _KEYBOARD,
                ],
            )
        self.assertGreaterEqual(api.timeouts[0], 30)

    async def test_legacy_photos_token_shape_is_understood(self) -> None:
        api = _MaxApi(
            upload_payload=lambda index: {"photos": {"98765": {"token": f"legacy-{index}"}}}
        )

        delivered, _ = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(
            api.messages[0]["json"]["attachments"],
            [{"type": "image", "payload": {"token": "legacy-1"}}, _KEYBOARD],
        )

    async def test_attachment_not_ready_is_retried_then_succeeds(self) -> None:
        api = _MaxApi(
            messages=[
                httpx.Response(400, json=_NOT_READY),
                httpx.Response(400, json=_NOT_READY),
                httpx.Response(200, json={"message": {}}),
            ]
        )

        delivered, sleep = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(len(api.uploads), 1)
        self.assertEqual(len(api.messages), 3)
        # Это не «плохая разметка»: повторяем тот же html с фото, а не плоский текст.
        for message in api.messages:
            self.assertEqual(message["json"]["format"], "html")
            self.assertEqual(
                message["json"]["attachments"],
                [{"type": "image", "payload": {"token": "token-1"}}, _KEYBOARD],
            )
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [0.5, 1.0])

    async def test_attachment_never_ready_falls_back_to_text(self) -> None:
        api = _MaxApi(messages=[httpx.Response(400, json=_NOT_READY)] * 4)

        delivered, sleep = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(len(api.messages), 5)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [0.5, 1.0, 2.0])
        with_images = api.messages[:4]
        for message in with_images:
            self.assertEqual(message["json"]["format"], "html")
            self.assertEqual(len(message["json"]["attachments"]), 2)
        text_only = api.messages[4]["json"]
        self.assertEqual(text_only["format"], "html")
        self.assertEqual(text_only["text"], "<b>Возврат</b>")
        self.assertEqual(text_only["attachments"], [_KEYBOARD])

    async def test_upload_slot_failure_falls_back_to_text(self) -> None:
        api = _MaxApi(slot_status=500)

        delivered, _ = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(api.uploads, [])
        self.assertEqual(len(api.messages), 1)
        self.assertEqual(api.messages[0]["json"]["text"], "<b>Возврат</b>")
        self.assertEqual(api.messages[0]["json"]["attachments"], [_KEYBOARD])

    async def test_upload_server_failure_falls_back_to_text(self) -> None:
        api = _MaxApi(upload_status=502)

        delivered, _ = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1), _photo(2)]
        )

        self.assertEqual(delivered, 1)
        # Каждое фото попробовали картинкой и файлом.
        self.assertEqual(
            [upload["type"] for upload in api.uploads], ["image", "file", "image", "file"]
        )
        self.assertEqual(len(api.messages), 1)
        self.assertEqual(api.messages[0]["json"]["attachments"], [_KEYBOARD])

    async def test_upload_timeouts_stop_after_two_photos(self) -> None:
        api = _MaxApi(upload_status=httpx.WriteTimeout)

        delivered, _ = await self._notify(
            api,
            recipients=[("chat_id", 100), ("user_id", 200)],
            photos=[_photo(1), _photo(2), _photo(3), _photo(4)],
        )

        # Не четыре загрузки по 30 с подряд, а две — и сразу текст.
        self.assertEqual(delivered, 2)
        self.assertEqual(
            [(upload["type"], upload["parts"]["data"][0]) for upload in api.uploads],
            [("image", "return-1.jpg"), ("image", "return-2.jpg")],
        )
        self.assertEqual(len(api.slots), 2)
        self.assertEqual(
            [message["params"] for message in api.messages],
            [{"chat_id": "100"}, {"user_id": "200"}],
        )
        for message in api.messages:
            self.assertEqual(message["json"]["attachments"], [_KEYBOARD])

    async def test_upload_server_errors_stop_after_two_photos(self) -> None:
        api = _MaxApi(upload_status=502)

        delivered, _ = await self._notify(
            api,
            recipients=[("chat_id", 100)],
            photos=[_photo(1), _photo(2), _photo(3), _photo(4)],
        )

        self.assertEqual(delivered, 1)
        # Картинка и файл — одна неудачная попытка фото; фото 3 и 4 не грузим.
        self.assertEqual(
            [(upload["type"], upload["parts"]["data"][0]) for upload in api.uploads],
            [
                ("image", "return-1.jpg"),
                ("file", "return-1.jpg"),
                ("image", "return-2.jpg"),
                ("file", "return-2.jpg"),
            ],
        )
        self.assertEqual(len(api.messages), 1)
        self.assertEqual(api.messages[0]["json"]["attachments"], [_KEYBOARD])

    async def test_uploaded_photos_still_go_when_later_uploads_are_stopped(self) -> None:
        api = _MaxApi(
            upload_status=lambda upload_type, filename: (
                502 if filename in {"return-2.jpg", "return-3.jpg"} else 200
            )
        )

        delivered, _ = await self._notify(
            api,
            recipients=[("chat_id", 100)],
            photos=[_photo(1), _photo(2), _photo(3), _photo(4)],
        )

        self.assertEqual(delivered, 1)
        self.assertNotIn(
            "return-4.jpg", [upload["parts"]["data"][0] for upload in api.uploads]
        )
        self.assertEqual(
            api.messages[0]["json"]["attachments"],
            [{"type": "image", "payload": {"token": "token-1"}}, _KEYBOARD],
        )

    async def test_rejected_image_is_sent_as_file(self) -> None:
        # Картинку MAX не принял (например, 8160×6120) — то же фото уходит файлом.
        api = _MaxApi(
            upload_status=lambda upload_type, filename: (
                400 if upload_type == "image" and filename == "return-2.jpg" else 200
            )
        )

        delivered, _ = await self._notify(
            api,
            recipients=[("chat_id", 100), ("user_id", 200)],
            photos=[_photo(1), _photo(2)],
        )

        self.assertEqual(delivered, 2)
        self.assertEqual(
            [slot.url.params["type"] for slot in api.slots], ["image", "image", "file"]
        )
        self.assertEqual(
            [(upload["type"], upload["parts"]["data"][0]) for upload in api.uploads],
            [("image", "return-1.jpg"), ("image", "return-2.jpg"), ("file", "return-2.jpg")],
        )
        for message in api.messages:
            self.assertEqual(
                message["json"]["attachments"],
                [
                    {"type": "image", "payload": {"token": "token-1"}},
                    {"type": "file", "payload": {"token": "token-3"}},
                    _KEYBOARD,
                ],
            )

    async def test_file_token_from_upload_slot_is_understood(self) -> None:
        def slot_payload(upload_type, index):
            payload = {"url": f"{_UPLOAD_HOST}/upload.do?type={upload_type}&slot={index}"}
            if upload_type == "file":
                payload["token"] = "slot-token"
            return payload

        api = _MaxApi(
            slot_payload=slot_payload,
            upload_status=lambda upload_type, filename: 400 if upload_type == "image" else 200,
            upload_payload=lambda index: None,
        )

        delivered, _ = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 1)
        self.assertEqual(
            api.messages[0]["json"]["attachments"],
            [{"type": "file", "payload": {"token": "slot-token"}}, _KEYBOARD],
        )

    async def test_upload_timeout_is_not_repeated_as_file(self) -> None:
        api = _MaxApi(upload_status=httpx.ReadTimeout)

        delivered, _ = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1)]
        )

        # Медленную загрузку не повторяем: текст операторам и так ждёт её.
        self.assertEqual(delivered, 1)
        self.assertEqual([upload["type"] for upload in api.uploads], ["image"])
        self.assertEqual(len(api.messages), 1)
        self.assertEqual(api.messages[0]["json"]["attachments"], [_KEYBOARD])

    async def test_read_timeout_on_message_with_photos_sends_no_duplicate_text(self) -> None:
        api = _MaxApi(messages=[httpx.ReadTimeout])

        delivered, _ = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1)]
        )

        # Сообщение с фото могло дойти: текст без фото был бы дублем.
        self.assertEqual(delivered, 0)
        self.assertEqual(len(api.messages), 1)
        self.assertEqual(len(api.messages[0]["json"]["attachments"]), 2)

    async def test_write_timeout_on_message_with_photos_sends_no_duplicate_text(self) -> None:
        api = _MaxApi(messages=[httpx.WriteTimeout])

        delivered, _ = await self._notify(
            api, recipients=[("chat_id", 100), ("chat_id", 200)], photos=[_photo(1)]
        )

        # Второй адресат не пострадал.
        self.assertEqual(delivered, 1)
        self.assertEqual(len(api.messages), 2)
        for message in api.messages:
            self.assertEqual(len(message["json"]["attachments"]), 2)

    async def test_connect_error_on_message_with_photos_falls_back_to_text(self) -> None:
        api = _MaxApi(messages=[httpx.ConnectError, httpx.Response(200, json={"message": {}})])

        delivered, _ = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1)]
        )

        # Соединение не установилось — сообщение точно не дошло.
        self.assertEqual(delivered, 1)
        self.assertEqual(len(api.messages), 2)
        self.assertEqual(api.messages[1]["json"]["attachments"], [_KEYBOARD])

    async def test_message_with_images_rejected_falls_back_to_text(self) -> None:
        api = _MaxApi(
            messages=[
                httpx.Response(400, text="bad format"),
                httpx.Response(400, text="bad attachment"),
                httpx.Response(200, json={"message": {}}),
            ]
        )

        delivered, sleep = await self._notify(
            api, recipients=[("chat_id", 100)], photos=[_photo(1)]
        )

        self.assertEqual(delivered, 1)
        sleep.assert_not_awaited()
        self.assertEqual(len(api.messages), 3)
        # html с фото → плоский с фото → html без фото.
        self.assertEqual(api.messages[0]["json"]["format"], "html")
        self.assertNotIn("format", api.messages[1]["json"])
        self.assertEqual(len(api.messages[1]["json"]["attachments"]), 2)
        self.assertEqual(api.messages[2]["json"]["attachments"], [_KEYBOARD])

    async def test_without_photos_nothing_is_uploaded(self) -> None:
        api = _MaxApi()

        delivered, _ = await self._notify(api, recipients=[("chat_id", 100)])

        self.assertEqual(delivered, 1)
        self.assertEqual(api.slots, [])
        self.assertEqual(api.uploads, [])
        self.assertEqual(api.timeouts, [10])
        self.assertEqual(api.messages[0]["json"]["attachments"], [_KEYBOARD])


if __name__ == "__main__":
    unittest.main()
