"""Единая точка отправки админских уведомлений: Telegram + MAX.

Все продуктовые вызовы (верификация, поддержка, просрочки, лиды
франшизы, инвентарь) идут сюда, а не в конкретный мессенджер. Текст
пишется один раз в HTML — каждый транспорт сам решает, что с ним делать.

Каналы независимы: если у одного нет токена или подписчиков, он молча
пропускается, второй всё равно доставит. Ошибка одного канала не мешает
другому — ``gather`` собирает результаты с ``return_exceptions=True``.
"""

from __future__ import annotations

import asyncio
import logging
from html import escape as escape_html
from typing import Iterable
from uuid import UUID

from backend.utils.max_bot import notify_admins as _notify_max
from backend.utils.telegram_bot import InlineButton, notify_admins as _notify_telegram

logger = logging.getLogger(__name__)


def _delivered(result: object, channel: str) -> int:
    if isinstance(result, BaseException):
        logger.exception(
            "Admin notification failed for %s channel", channel, exc_info=result
        )
        return 0
    return int(result or 0)


async def notify_admins(
    text: str,
    *,
    buttons: Iterable[InlineButton] = (),
    city_id: UUID | None = None,
) -> int:
    """Шлёт ``text`` админам во все настроенные каналы.

    :param buttons: список ``(label, url)``; каждая кнопка занимает свой ряд.
    :param city_id: город события. Уведомление получат подписчики сети и
        подписчики этого города (франшизы); без города — только подписчики
        сети. Правило одинаковое в обоих каналах.
    :return: суммарное число доставок по всем каналам. ``0`` означает, что
        уведомление не ушло никуда — вызывающий код может это залогировать.
    """

    prepared = tuple(buttons)
    telegram_result, max_result = await asyncio.gather(
        _notify_telegram(text, buttons=prepared, city_id=city_id),
        _notify_max(text, buttons=prepared, city_id=city_id),
        return_exceptions=True,
    )
    return _delivered(telegram_result, "telegram") + _delivered(max_result, "max")


def fire_and_forget_notify(
    text: str,
    *,
    buttons: Iterable[InlineButton] = (),
    city_id: UUID | None = None,
) -> None:
    """Удобная обёртка для синхронного контекста или кода после
    ``await db.commit()``: запускает задачу в текущем event loop и не
    дожидается её завершения.

    Если event loop недоступен (например, тест без ``pytest-asyncio``),
    падать не будем — просто залогируем.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running event loop, skipping admin notification")
        return

    loop.create_task(notify_admins(text, buttons=tuple(buttons), city_id=city_id))


__all__ = [
    "InlineButton",
    "escape_html",
    "fire_and_forget_notify",
    "notify_admins",
]
