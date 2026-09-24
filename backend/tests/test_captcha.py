"""Картинка-капча публичных форм: токен, одна попытка, срок, картинка, ручка."""

from __future__ import annotations

import io
import time
import unittest

from fastapi import HTTPException
from PIL import Image
from starlette.requests import Request
from starlette.responses import Response

from backend.routers import captcha as captcha_router
from backend.utils.captcha import (
    CAPTCHA_TTL_SECONDS,
    CaptchaError,
    issue_captcha,
    render_captcha_png,
    reset_used_captchas,
    verify_captcha,
)


def _request(ip: str = "203.0.113.20") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/captcha",
            "headers": [],
            "client": (ip, 51234),
        }
    )


class CaptchaTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_used_captchas()

    def assertRejected(self, code: str, token: str | None, answer: str | None, **kwargs) -> None:
        with self.assertRaises(CaptchaError) as ctx:
            verify_captcha(token, answer, **kwargs)
        self.assertEqual(ctx.exception.code, code)
        self.assertTrue(ctx.exception.detail["message"])

    def test_right_answer_passes_even_with_spaces(self) -> None:
        challenge = issue_captcha()
        spaced = f" {challenge.answer[:2]} {challenge.answer[2:]} "
        verify_captcha(challenge.token, spaced)

    def test_answer_is_not_readable_from_the_token(self) -> None:
        challenge = issue_captcha()
        self.assertNotIn(challenge.answer, challenge.token)

    def test_token_gives_exactly_one_attempt(self) -> None:
        """Иначе цифры можно было бы перебрать на одной картинке."""

        challenge = issue_captcha()
        self.assertRejected("CAPTCHA_INVALID", challenge.token, "00000")
        self.assertRejected("CAPTCHA_EXPIRED", challenge.token, challenge.answer)

    def test_solved_token_cannot_be_replayed(self) -> None:
        challenge = issue_captcha()
        verify_captcha(challenge.token, challenge.answer)
        self.assertRejected("CAPTCHA_EXPIRED", challenge.token, challenge.answer)

    def test_token_expires(self) -> None:
        issued_at = time.time()
        challenge = issue_captcha(now=issued_at)
        self.assertRejected(
            "CAPTCHA_EXPIRED",
            challenge.token,
            challenge.answer,
            now=issued_at + CAPTCHA_TTL_SECONDS + 1,
        )

    def test_extended_expiry_breaks_the_signature(self) -> None:
        challenge = issue_captcha()
        nonce, expires, check, sig = challenge.token.split(".")
        forged = ".".join([nonce, str(int(expires) + 86_400), check, sig])
        self.assertRejected("CAPTCHA_INVALID", forged, challenge.answer)

    def test_missing_parts_ask_for_the_captcha(self) -> None:
        challenge = issue_captcha()
        self.assertRejected("CAPTCHA_REQUIRED", None, None)
        self.assertRejected("CAPTCHA_REQUIRED", challenge.token, "   ")
        self.assertRejected("CAPTCHA_REQUIRED", "", challenge.answer)

    def test_garbage_tokens_are_rejected_not_crashing(self) -> None:
        for token in ("abc", "a.b.c", "a.b.c.d", "ё.1.ж.з", "....", "x" * 200):
            self.assertRejected("CAPTCHA_INVALID", token, "23456")


class CaptchaImageTests(unittest.TestCase):
    def test_image_is_a_retina_png(self) -> None:
        png = render_captcha_png("23456")
        image = Image.open(io.BytesIO(png))
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.size, (300, 100))
        self.assertLess(len(png), 20_000)

    def test_images_differ_for_the_same_digits(self) -> None:
        self.assertNotEqual(render_captcha_png("23456"), render_captcha_png("23456"))


class CaptchaEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        captcha_router._limiter.reset()
        reset_used_captchas()

    async def test_endpoint_returns_uncached_image_and_token(self) -> None:
        response = Response()
        payload = await captcha_router.get_captcha(_request(), response)

        data = payload["data"]
        self.assertTrue(data["image"].startswith("data:image/png;base64,"))
        self.assertEqual(len(data["token"].split(".")), 4)
        self.assertEqual(data["expiresIn"], CAPTCHA_TTL_SECONDS)
        self.assertNotIn("answer", data)
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_flood_from_one_address_is_cut(self) -> None:
        for _ in range(captcha_router._limiter.per_ip):
            await captcha_router.get_captcha(_request(), Response())

        with self.assertRaises(HTTPException) as ctx:
            await captcha_router.get_captcha(_request(), Response())
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail["code"], "TOO_MANY_REQUESTS")

        # Соседний адрес при этом капчу получает.
        await captcha_router.get_captcha(_request("203.0.113.21"), Response())


if __name__ == "__main__":
    unittest.main()
