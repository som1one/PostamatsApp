import unittest
from unittest.mock import patch

import httpx

from backend.utils.sms_ru import SmsRuError, send_auth_code


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, response=None, error=None, sink=None, **_kwargs):
        self._response = response
        self._error = error
        self._sink = sink if sink is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params):
        self._sink["url"] = url
        self._sink["params"] = params
        if self._error is not None:
            raise self._error
        return self._response


class SmsRuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from backend.utils import sms_ru

        self.sms_ru = sms_ru
        self.original_api_id = sms_ru.settings.SMS_RU_API_ID
        self.original_timeout = sms_ru.settings.SMS_RU_TIMEOUT_SECONDS
        sms_ru.settings.SMS_RU_API_ID = "test-api-id"
        sms_ru.settings.SMS_RU_TIMEOUT_SECONDS = 3

    def tearDown(self):
        self.sms_ru.settings.SMS_RU_API_ID = self.original_api_id
        self.sms_ru.settings.SMS_RU_TIMEOUT_SECONDS = self.original_timeout

    async def test_send_auth_code_success(self):
        sink = {}
        response = _FakeResponse(
            200,
            {
                "status": "OK",
                "status_code": 100,
                "sms": {
                    "79216928433": {
                        "status": "OK",
                        "status_code": 100,
                        "sms_id": "000000-10000000",
                    }
                },
            },
        )

        with patch.object(
            self.sms_ru.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: _FakeAsyncClient(response=response, sink=sink, **kwargs),
        ):
            sms_id = await send_auth_code("+79216928433", "1234")

        self.assertEqual(sms_id, "000000-10000000")
        self.assertEqual(sink["url"], self.sms_ru.SMS_RU_SEND_URL)
        self.assertEqual(sink["params"]["to"], "79216928433")
        self.assertEqual(sink["params"]["json"], 1)
        self.assertEqual(sink["params"]["msg"], "Код входа в naprokatberu: 1234")

    async def test_send_auth_code_rejects_top_level_error(self):
        response = _FakeResponse(
            200,
            {
                "status": "ERROR",
                "status_code": 201,
                "sms": {},
            },
        )

        with patch.object(
            self.sms_ru.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: _FakeAsyncClient(response=response, **kwargs),
        ):
            with self.assertRaises(SmsRuError) as context:
                await send_auth_code("+79216928433", "1234")

        self.assertEqual(context.exception.code, "AUTH_SMS_SEND_FAILED")
        self.assertEqual(context.exception.status_code, 502)

    async def test_send_auth_code_rejects_recipient_error(self):
        response = _FakeResponse(
            200,
            {
                "status": "OK",
                "status_code": 100,
                "sms": {
                    "79216928433": {
                        "status": "ERROR",
                        "status_code": 207,
                        "status_text": "blocked",
                    }
                },
            },
        )

        with patch.object(
            self.sms_ru.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: _FakeAsyncClient(response=response, **kwargs),
        ):
            with self.assertRaises(SmsRuError) as context:
                await send_auth_code("+79216928433", "1234")

        self.assertEqual(context.exception.code, "AUTH_SMS_SEND_FAILED")
        self.assertEqual(context.exception.status_code, 502)

    async def test_send_auth_code_rejects_request_failure(self):
        error = httpx.RequestError("boom", request=httpx.Request("GET", "https://sms.ru"))

        with patch.object(
            self.sms_ru.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: _FakeAsyncClient(error=error, **kwargs),
        ):
            with self.assertRaises(SmsRuError) as context:
                await send_auth_code("+79216928433", "1234")

        self.assertEqual(context.exception.code, "AUTH_SMS_PROVIDER_ERROR")
        self.assertEqual(context.exception.status_code, 502)
