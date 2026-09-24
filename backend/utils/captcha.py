"""Своя картинка-капча для публичных форм (обратная связь).

Рисуем её сами (Pillow), без Яндекс SmartCaptcha и reCAPTCHA: не нужны ни
ключи, ни аккаунт в облаке, данные посетителя не уходят третьим лицам, и
форма не ломается, если чужой сервис недоступен.

Хранилища нет. ``issue_captcha`` отдаёт PNG с цифрами и токен
``nonce.expires.check.sig``:

* ``check`` — HMAC от nonce и правильного ответа. Самого ответа в токене нет,
  а подобрать его офлайн без секрета нельзя;
* ``sig`` — HMAC от остального токена: по нему видно, что токен выдали мы,
  ещё до сверки ответа.

Каждый токен — одна попытка: nonce запоминаем при первой же проверке, верной
или нет, иначе цифры можно было бы перебрать на одной картинке. Использованные
nonce живут в памяти процесса до конца срока токена — на проде бэкенд
работает одним воркером. После рестарта уже решённую капчу можно отправить
ещё раз, но лимитер формы при этом никуда не девается.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import io
import math
import random
import secrets
import threading
import time
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from backend.core.settings import settings

CAPTCHA_TTL_SECONDS = 30 * 60
CAPTCHA_LENGTH = 5
# Без 0 и 1: их путают с буквами O, I и l.
_ALPHABET = "23456789"

_MESSAGES = {
    "CAPTCHA_REQUIRED": (
        "Нужен код с картинки. Обновите страницу или приложение и попробуйте ещё раз."
    ),
    "CAPTCHA_INVALID": "Неверный код с картинки. Введите новый.",
    "CAPTCHA_EXPIRED": "Код с картинки устарел. Введите новый.",
}

# Потолок на список использованных nonce, чтобы флуд не съел память.
_MAX_USED = 20_000
_used_nonces: dict[str, int] = {}

# Если секретов в окружении нет (dev, тесты), подписываем случайным ключом
# процесса: токены просто перестают действовать после рестарта.
_PROCESS_KEY = secrets.token_bytes(32)


class CaptchaError(Exception):
    """Капча не пройдена; ``detail`` готов для ``HTTPException``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": _MESSAGES[self.code]}


@dataclass(frozen=True)
class CaptchaChallenge:
    token: str
    image_png: bytes
    # Нужен только тестам — клиенту никогда не отдаётся.
    answer: str

    @property
    def image_data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.image_png).decode("ascii")


def _key() -> bytes:
    base = settings.JWT_SECRET_KEY or settings.ADMIN_JWT_SECRET_KEY
    if not base:
        return _PROCESS_KEY
    # Отдельный ключ из общего секрета, чтобы подпись капчи нельзя было
    # выдать за подпись чего-то ещё.
    return hmac.new(base.encode("utf-8"), b"captcha-v1", hashlib.sha256).digest()


def _mac(*parts: str) -> str:
    digest = hmac.new(_key(), ".".join(parts).encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:16]).decode("ascii").rstrip("=")


def _same(left: str, right: str) -> bool:
    # compare_digest на str падает от не-ASCII, а токен присылает кто угодно.
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _normalize(answer: str | None) -> str:
    return "".join((answer or "").split())


def issue_captcha(*, now: float | None = None) -> CaptchaChallenge:
    answer = "".join(secrets.choice(_ALPHABET) for _ in range(CAPTCHA_LENGTH))
    nonce = secrets.token_urlsafe(12)
    expires = str(int(now if now is not None else time.time()) + CAPTCHA_TTL_SECONDS)
    check = _mac("answer", nonce, answer)
    sig = _mac("token", nonce, expires, check)
    return CaptchaChallenge(
        token=f"{nonce}.{expires}.{check}.{sig}",
        image_png=render_captcha_png(answer),
        answer=answer,
    )


def _remember_used(nonce: str, expires: int, now: int) -> None:
    if len(_used_nonces) >= _MAX_USED:
        for key in [key for key, until in _used_nonces.items() if until < now]:
            del _used_nonces[key]
        if len(_used_nonces) >= _MAX_USED:
            _used_nonces.clear()
    _used_nonces[nonce] = expires


def verify_captcha(token: str | None, answer: str | None, *, now: float | None = None) -> None:
    """Пропускает только верный ответ на живой, ещё не использованный токен."""

    token = (token or "").strip()
    answer = _normalize(answer)
    if not token or not answer:
        raise CaptchaError("CAPTCHA_REQUIRED")

    parts = token.split(".")
    if len(parts) != 4:
        raise CaptchaError("CAPTCHA_INVALID")
    nonce, expires_raw, check, sig = parts
    if not _same(sig, _mac("token", nonce, expires_raw, check)):
        raise CaptchaError("CAPTCHA_INVALID")

    current = int(now if now is not None else time.time())
    expires = int(expires_raw)
    if expires < current or nonce in _used_nonces:
        raise CaptchaError("CAPTCHA_EXPIRED")
    _remember_used(nonce, expires, current)

    if not _same(check, _mac("answer", nonce, answer)):
        raise CaptchaError("CAPTCHA_INVALID")


def reset_used_captchas() -> None:
    """Забывает использованные токены (нужно тестам между кейсами)."""

    _used_nonces.clear()


# --- Картинка ---------------------------------------------------------------

# Рисуем в 2x, на странице картинка стоит 150×50: так она чёткая на ретине.
_SCALE = 2
_WIDTH, _HEIGHT = 150 * _SCALE, 50 * _SCALE
# Цвета из палитры сайта: фон — --surface, цифры — --text, --text-soft,
# --primary-dark и --ink, крапинки — --muted, --line-strong, --accent-warm.
_BACKGROUND = (255, 250, 245)
_INKS = [(43, 36, 31), (79, 67, 61), (148, 3, 3), (24, 24, 24)]
_SPECKS = [(125, 111, 100), (216, 196, 177), (212, 176, 134), (43, 36, 31)]

# Ручка рисует картинку в пуле потоков, а шрифты из кэша общие: FreeType не
# обещает, что один шрифт можно рисовать из двух потоков сразу. Картинка
# рисуется ~5 мс, так что очередь здесь ничего не тормозит.
_RENDER_LOCK = threading.Lock()


@functools.lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont:
    # Встроенный в Pillow Aileron: отдельный файл шрифта в образ не нужен.
    return ImageFont.load_default(size=size)


def render_captcha_png(text: str) -> bytes:
    with _RENDER_LOCK:
        return _render(text)


def _render(text: str) -> bytes:
    rng = random.SystemRandom()
    image = Image.new("RGB", (_WIDTH, _HEIGHT), _BACKGROUND)

    step = _WIDTH / (len(text) + 1)
    for index, char in enumerate(text):
        size = rng.randint(28, 33) * _SCALE
        ink = rng.choice(_INKS)
        tile = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text(
            (size, size),
            char,
            font=_font(size),
            fill=ink,
            anchor="mm",
            stroke_width=_SCALE,
            stroke_fill=ink,
        )
        tile = tile.rotate(rng.uniform(-22, 22), resample=Image.Resampling.BICUBIC)
        center_x = step * (index + 1) + rng.uniform(-4, 4) * _SCALE
        center_y = _HEIGHT / 2 + rng.uniform(-3.5, 3.5) * _SCALE
        image.paste(
            tile,
            (int(center_x - tile.width / 2), int(center_y - tile.height / 2)),
            tile,
        )

    # Волна по всей картинке: цифры перестают быть ровными глифами шрифта.
    amplitude = rng.uniform(2.0, 3.5) * _SCALE
    period = rng.uniform(0.7, 1.2) * _WIDTH
    phase = rng.uniform(0, 2 * math.pi)
    strip = 6 * _SCALE
    mesh = []
    for x in range(0, _WIDTH, strip):
        x2 = min(x + strip, _WIDTH)
        dy1 = amplitude * math.sin(2 * math.pi * x / period + phase)
        dy2 = amplitude * math.sin(2 * math.pi * x2 / period + phase)
        mesh.append(
            ((x, 0, x2, _HEIGHT), (x, dy1, x, _HEIGHT + dy1, x2, _HEIGHT + dy2, x2, dy2))
        )
    image = image.transform(
        image.size,
        Image.Transform.MESH,
        mesh,
        Image.Resampling.BICUBIC,
        fillcolor=_BACKGROUND,
    )

    draw = ImageDraw.Draw(image)
    # Две линии через все цифры их же цветами — по цвету не отфильтровать.
    for _ in range(2):
        base_y = rng.uniform(0.3, 0.7) * _HEIGHT
        wave = rng.uniform(0.12, 0.25) * _HEIGHT
        wave_period = rng.uniform(0.5, 1.1) * _WIDTH
        wave_phase = rng.uniform(0, 2 * math.pi)
        points = [
            (x, base_y + wave * math.sin(2 * math.pi * x / wave_period + wave_phase))
            for x in range(-4 * _SCALE, _WIDTH + 4 * _SCALE, 3 * _SCALE)
        ]
        draw.line(points, fill=rng.choice(_INKS), width=int(1.5 * _SCALE), joint="curve")

    for _ in range(70):
        x = rng.uniform(0, _WIDTH)
        y = rng.uniform(0, _HEIGHT)
        radius = rng.uniform(0.6, 1.4) * _SCALE
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=rng.choice(_SPECKS))

    buffer = io.BytesIO()
    # Палитра из 48 цветов втрое уменьшает PNG (~5 КБ), на глаз разницы нет.
    image.quantize(colors=48).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


__all__ = [
    "CAPTCHA_TTL_SECONDS",
    "CaptchaChallenge",
    "CaptchaError",
    "issue_captcha",
    "render_captcha_png",
    "reset_used_captchas",
    "verify_captcha",
]
