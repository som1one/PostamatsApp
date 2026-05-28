"""Минимальная интеграция с Telegram Bot API для админских уведомлений.

Использование (fire-and-forget):

    fire_and_forget_notify(
        "<b>Новая заявка на верификацию</b>\\n+7 999 ***",
        buttons=[("Открыть в админке", "https://.../admin/?section=verification&user=...")],
    )

Особенности:

- Если ``TELEGRAM_ADMIN_BOT_TOKEN`` не задан, функция тихо ничего не
  делает. Это удобно в dev и в тестах.
- Адресаты определяются динамически: сначала пытаемся взять активных
  подписчиков из БД, и только если БД пустая или недоступна — падаем
  на ``settings.TELEGRAM_ADMIN_CHAT_IDS`` (старый CSV-режим).
- Отправка идёт по списку chat_id параллельно. Ошибки логируются, но
  не пробрасываются наружу — клиентский запрос не должен падать
  из-за телеги.
- Сообщение форматируется как HTML, поэтому пользовательский текст,
  который мы хотим показать (имя, телефон, документ), нужно прогонять
  через :func:`escape_html` (re-export ``html.escape``).
"""

from __future__ import annotations

import asyncio
import logging
from html import escape as escape_html
from typing import Iterable, Sequence

import httpx

from backend.core.database import SessionLocal
from backend.core.settings import settings

logger = logging.getLogger(__name__)

# Inline keyboard with a single URL button.
InlineButton = tuple[str, str]


def _telegram_api_url(method: str) -> str:
    token = settings.TELEGRAM_ADMIN_BOT_TOKEN
    if not token:
        raise RuntimeError("TELEGRAM_ADMIN_BOT_TOKEN is not configured")
    return f"https://api.telegram.org/bot{token}/{method}"


def _build_reply_markup(buttons: Sequence[InlineButton]) -> dict | None:
    if not buttons:
        return None
    return {
        "inline_keyboard": [
            [{"text": text, "url": url}] for text, url in buttons if text and url
        ]
    }


async def _send_one(
    client: httpx.AsyncClient,
    chat_id: str,
    text: str,
    reply_markup: dict | None,
) -> None:
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    try:
        response = await client.post(_telegram_api_url("sendMessage"), json=payload)
    except httpx.RequestError:
        logger.exception("Telegram sendMessage failed for chat %s", chat_id)
        return

    if response.status_code >= 400:
        # 403 — пользователь не нажал /start или заблокировал бота.
        # 400 — кривой chat_id или markdown. Логируем, но не падаем.
        logger.warning(
            "Telegram sendMessage non-2xx for chat %s: %s %s",
            chat_id,
            response.status_code,
            response.text[:200],
        )


async def _resolve_chat_ids() -> list[str]:
    """Определяет получателей для текущей рассылки.

    Сначала пытаемся взять активных (включённых и привязанных)
    подписчиков из БД. Если в БД ни одного активного — fallback на
    CSV из настроек, чтобы старый деплой без миграции продолжал
    работать.
    """

    try:
        # Импорт внутри функции, чтобы избежать кругового импорта на
        # этапе загрузки модуля (telegram_admin_subscribers тоже шлёт
        # запросы и в будущем может тянуть этот модуль).
        from backend.utils.telegram_admin_subscribers import get_active_chat_ids

        async with SessionLocal() as db:
            ids = await get_active_chat_ids(db)
        if ids:
            return ids
    except Exception:
        logger.exception("Failed to read telegram subscribers from DB")

    return [str(item) for item in settings.TELEGRAM_ADMIN_CHAT_IDS if item]


async def notify_admins(
    text: str,
    *,
    buttons: Iterable[InlineButton] = (),
    chat_ids: Sequence[str] | None = None,
) -> None:
    """Шлёт ``text`` всем активным подписчикам.

    :param buttons: список ``(label, url)`` для inline-клавиатуры.
        Каждая кнопка занимает свой ряд.
    :param chat_ids: переопределение получателей. Если ``None``,
        берутся из БД (или CSV-fallback из настроек).
    """

    if not settings.TELEGRAM_ADMIN_BOT_TOKEN:
        logger.debug("Telegram admin notifications skipped: no bot token")
        return

    if chat_ids is not None:
        targets = list(chat_ids)
    else:
        targets = await _resolve_chat_ids()

    if not targets:
        logger.debug("Telegram admin notifications skipped: no recipients")
        return

    reply_markup = _build_reply_markup(tuple(buttons))
    timeout = max(1.0, settings.TELEGRAM_API_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout) as client:
        await asyncio.gather(
            *(_send_one(client, str(chat), text, reply_markup) for chat in targets),
            return_exceptions=True,
        )


def fire_and_forget_notify(
    text: str,
    *,
    buttons: Iterable[InlineButton] = (),
) -> None:
    """Удобная обёртка для использования из синхронного контекста или
    после ``await db.commit()``: запускает задачу в текущем event loop и
    не дожидается её завершения.

    Если event loop недоступен (например, тест без ``pytest-asyncio``),
    падать не будем — просто залогируем.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running event loop, skipping telegram notification")
        return

    loop.create_task(notify_admins(text, buttons=tuple(buttons)))


__all__ = [
    "InlineButton",
    "escape_html",
    "fire_and_forget_notify",
    "notify_admins",
]
