"""Публичная заявка на франшизу (страница /franchise) → Telegram админам.

Заявка нигде не сохраняется: единственный канал доставки — админский
Telegram-бот, те же подписчики, что получают верификации и поддержку.
Поэтому заявку, которая не доехала до телеги (нет токена, никто не
подписан, Telegram ответил ошибкой), дублируем в лог на уровне ERROR —
иначе лид пропал бы бесследно.

Эндпоинт публичный и шлёт сообщения в мессенджер, то есть это удобная
мишень для спама. Отсюда простой лимитер в памяти процесса: не больше
``_PER_IP_LIMIT`` заявок с одного IP за ``_PER_IP_WINDOW`` и не больше
``_GLOBAL_LIMIT`` заявок суммарно за ``_GLOBAL_WINDOW``. Счётчики живут
в процессе (у каждого воркера свои) и обнуляются при рестарте — для
защиты от «нажал десять раз» и мелкого флуда этого достаточно, а
глобальный потолок ограничивает ущерб, даже если IP подделали.
"""

from __future__ import annotations

import logging
import time
from collections import deque

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from backend.utils.phone_utils import normalize_phone_for_storage
from backend.utils.telegram_bot import escape_html, notify_admins

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/franchise", tags=["public-franchise"])

_PER_IP_LIMIT = 3
_PER_IP_WINDOW = 10 * 60
_GLOBAL_LIMIT = 30
_GLOBAL_WINDOW = 60 * 60

# Чтобы словарь не рос бесконечно на длинной сессии процесса.
_MAX_TRACKED_IPS = 512

_recent_by_ip: dict[str, deque[float]] = {}
_recent_global: deque[float] = deque()

# Минимум цифр в телефоне: 10 — это номер без кода страны (9991234567).
_MIN_PHONE_DIGITS = 10
_MAX_PHONE_DIGITS = 15


class FranchiseLeadPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    # Длину телефона проверяет _normalize_phone: так короткий номер даёт
    # понятный INVALID_PHONE, а не 422 от pydantic, который фронт покажет
    # общей ошибкой «не удалось отправить».
    phone: str = Field(..., min_length=1, max_length=32)
    city: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=2000)


def _client_ip(request: Request) -> str:
    """IP клиента с учётом того, что бэкенд стоит за Caddy.

    Заголовок подделывается кем угодно, поэтому на него завязан только
    per-IP лимит; настоящая страховка — глобальный потолок.
    """

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _prune(bucket: deque[float], window: float, now: float) -> None:
    while bucket and now - bucket[0] > window:
        bucket.popleft()


def _check_rate_limit(ip: str) -> bool:
    """True, если заявку можно принять. Побочно фиксирует попытку."""

    now = time.monotonic()

    _prune(_recent_global, _GLOBAL_WINDOW, now)
    if len(_recent_global) >= _GLOBAL_LIMIT:
        return False

    bucket = _recent_by_ip.get(ip)
    if bucket is None:
        if len(_recent_by_ip) >= _MAX_TRACKED_IPS:
            # Выкидываем тех, у кого окно уже истекло; если таких нет —
            # чистим словарь целиком, глобальный лимит всё равно на месте.
            stale = [
                key
                for key, values in _recent_by_ip.items()
                if not values or now - values[-1] > _PER_IP_WINDOW
            ]
            for key in stale:
                del _recent_by_ip[key]
            if len(_recent_by_ip) >= _MAX_TRACKED_IPS:
                _recent_by_ip.clear()
        bucket = deque()
        _recent_by_ip[ip] = bucket

    _prune(bucket, _PER_IP_WINDOW, now)
    if len(bucket) >= _PER_IP_LIMIT:
        return False

    bucket.append(now)
    _recent_global.append(now)
    return True


def _normalize_phone(raw: str) -> str:
    """Приводит телефон к виду, по которому менеджер сразу позвонит.

    Форму заполняют как привыкли — «8 900 123-45-67» или «9001234567».
    Считаем такие номера российскими и дотягиваем до +7: иначе в телегу
    прилетит нечто вроде «+89001234567», по чему не наберёшь в один тап.
    """

    try:
        phone = normalize_phone_for_storage(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="INVALID_PHONE") from exc

    digits = "".join(ch for ch in phone if ch.isdigit())
    if not (_MIN_PHONE_DIGITS <= len(digits) <= _MAX_PHONE_DIGITS):
        raise HTTPException(status_code=400, detail="INVALID_PHONE")

    if len(digits) == 11 and digits.startswith("8"):
        return f"+7{digits[1:]}"
    if len(digits) == 10:
        return f"+7{digits}"
    return phone


def build_lead_message(*, name: str, phone: str, city: str | None, comment: str | None) -> str:
    lines = [
        "🤝 <b>Заявка на франшизу</b>",
        f"👤 {escape_html(name)}",
        f"📞 {escape_html(phone)}",
    ]
    if city:
        lines.append(f"🏙 {escape_html(city)}")
    if comment:
        lines.append("")
        lines.append(f"💬 {escape_html(comment)}")
    return "\n".join(lines)


@router.post("/leads")
async def create_franchise_lead(
    request: Request,
    payload: FranchiseLeadPayload = Body(...),
):
    name = payload.name.strip()
    city = (payload.city or "").strip() or None
    comment = (payload.comment or "").strip() or None
    if not name:
        raise HTTPException(status_code=400, detail="INVALID_PAYLOAD")
    phone = _normalize_phone(payload.phone)

    if not _check_rate_limit(_client_ip(request)):
        raise HTTPException(status_code=429, detail="TOO_MANY_REQUESTS")

    lead_log = f"name={name!r} phone={phone!r} city={city!r} comment={comment!r}"
    logger.info("Franchise lead: %s", lead_log)

    delivered = await notify_admins(
        build_lead_message(name=name, phone=phone, city=city, comment=comment)
    )
    if not delivered:
        # Посетителю всё равно отвечаем успехом: заявку он отправил, а
        # разбираться с ботом — наша забота. Уровень ERROR здесь не для
        # драмы: приложение не настраивает logging, INFO-строки в вывод
        # контейнера не попадают, и это единственный шанс сохранить лид,
        # который не доехал до телеги.
        logger.error("Franchise lead NOT delivered to Telegram: %s", lead_log)

    return {"data": {"delivered": delivered}}
