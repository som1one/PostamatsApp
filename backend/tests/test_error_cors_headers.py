"""Ошибка 500 должна доезжать до браузера вместе с CORS-заголовками.

Без этого кросс-доменный ответ без Access-Control-Allow-Origin превращается
в браузере в TypeError «Failed to fetch»: пользователь видит непонятную
английскую строку, а настоящая причина (статус и detail) теряется — так и
случилось с отправкой документов на верификацию.
"""

from __future__ import annotations

import unittest

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.error_middleware import InternalErrorResponseMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    # Тот же порядок, что в backend/main.py: обработчик 500 внутри CORS.
    app.add_middleware(InternalErrorResponseMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://naprokatberu.ru"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.put("/boom")
    async def boom():  # pragma: no cover - тело не важно, важно исключение
        raise RuntimeError("disk on fire")

    @app.get("/ok")
    async def ok():
        return {"data": "ok"}

    return app


class ErrorCorsHeadersTest(unittest.IsolatedAsyncioTestCase):
    async def _request(self, method: str, path: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=_build_app(), raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(
                method,
                path,
                headers={"Origin": "https://naprokatberu.ru"},
            )

    async def test_unhandled_error_keeps_cors_headers(self):
        response = await self._request("PUT", "/boom")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "INTERNAL_ERROR"})
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://naprokatberu.ru",
        )

    async def test_normal_response_untouched(self):
        response = await self._request("GET", "/ok")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"data": "ok"})
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://naprokatberu.ru",
        )


class MainAppMiddlewareOrderTest(unittest.TestCase):
    """CORS обязан оставаться снаружи, иначе заголовки на 500 не навесятся."""

    def test_cors_wraps_internal_error_middleware(self):
        from backend.main import app

        classes = [middleware.cls for middleware in app.user_middleware]

        self.assertIn(CORSMiddleware, classes)
        self.assertIn(InternalErrorResponseMiddleware, classes)
        self.assertLess(
            classes.index(CORSMiddleware),
            classes.index(InternalErrorResponseMiddleware),
            "add_middleware кладёт слой наружу: CORS должен быть добавлен последним",
        )


if __name__ == "__main__":
    unittest.main()
