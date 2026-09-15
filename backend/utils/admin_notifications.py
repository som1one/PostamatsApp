"""Единая точка отправки админских уведомлений: Telegram + MAX.

Все продуктовые вызовы (верификация, поддержка, просрочки, лиды
франшизы, инвентарь) идут сюда, а не в конкретный мессенджер. Текст
пишется один раз в HTML — каждый транспорт сам решает, что с ним делать.

Каналы независимы: если у одного нет токена или подписчиков, он молча
пропускается, второй всё равно доставит. Ошибка одного канала не мешает
другому — ``gather`` собирает результаты с ``return_exceptions=True``.

К уведомлению можно приложить фото с диска (``photos``). Байты читаются
здесь один раз, в отдельном потоке, и одни и те же отдаются обоим каналам:
обработчик запроса к диску не ходит, а мессенджеры не перечитывают файл.
Читаем не всё подряд: фото больше лимита пропускаем, не открывая, а общий
объём на одно уведомление ограничен — задача держит байты в памяти, пока
идёт рассылка.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from html import escape as escape_html
from pathlib import Path
from typing import Iterable, Sequence
from uuid import UUID

from backend.utils.max_bot import notify_admins as _notify_max
from backend.utils.telegram_bot import (
    InlineButton,
    PhotoFile,
    notify_admins as _notify_telegram,
)

logger = logging.getLogger(__name__)

# Фоновые задачи fire_and_forget_notify. Event loop держит на задачи только
# слабые ссылки, и без этого набора долгая отправка фото может быть собрана
# сборщиком мусора посреди загрузки.
_background_tasks: set[asyncio.Task] = set()

# Одно фото: столько же принимает загрузка фото возврата, и больше Telegram
# не возьмёт через sendPhoto. Всё, что крупнее, на диск попало в обход
# клиента — такое в мессенджер не тащим.
_PHOTO_MAX_BYTES = 10 * 1024 * 1024

# Все фото одного уведомления вместе (у возврата их не больше четырёх).
_PHOTOS_TOTAL_MAX_BYTES = 4 * _PHOTO_MAX_BYTES


@dataclass(frozen=True)
class NotificationPhoto:
    """Фото к уведомлению: файл на диске, который отправим как есть."""

    filename: str
    mime_type: str
    path: Path


def _delivered(result: object, channel: str) -> int:
    if isinstance(result, BaseException):
        logger.exception(
            "Admin notification failed for %s channel", channel, exc_info=result
        )
        return 0
    return int(result or 0)


def _read_photo_files(photos: Sequence[NotificationPhoto]) -> list[PhotoFile]:
    loaded: list[PhotoFile] = []
    total = 0
    for photo in photos:
        try:
            size = photo.path.stat().st_size
            if size > _PHOTO_MAX_BYTES or total + size > _PHOTOS_TOTAL_MAX_BYTES:
                logger.warning(
                    "Notification photo is too large (%s bytes, %s already read), "
                    "skipping: %s",
                    size,
                    total,
                    photo.path,
                )
                continue
            with photo.path.open("rb") as file:
                # Не больше лимита, даже если файл успел вырасти после stat.
                content = file.read(_PHOTO_MAX_BYTES + 1)
        except OSError:
            # Файл могли удалить между загрузкой и отправкой — уведомление
            # всё равно уйдёт, просто без этого фото.
            logger.warning("Notification photo is not readable: %s", photo.path)
            continue
        if not content:
            logger.warning("Notification photo is empty: %s", photo.path)
            continue
        if len(content) > _PHOTO_MAX_BYTES or total + len(content) > _PHOTOS_TOTAL_MAX_BYTES:
            logger.warning("Notification photo grew past the limit, skipping: %s", photo.path)
            continue
        total += len(content)
        loaded.append((photo.filename, content, photo.mime_type))
    return loaded


async def _load_photos(photos: Sequence[NotificationPhoto]) -> list[PhotoFile]:
    if not photos:
        return []
    try:
        return await asyncio.to_thread(_read_photo_files, photos)
    except Exception:
        logger.exception("Failed to read notification photos, sending text only")
        return []


async def notify_admins(
    text: str,
    *,
    buttons: Iterable[InlineButton] = (),
    city_id: UUID | None = None,
    photos: Sequence[NotificationPhoto] = (),
) -> int:
    """Шлёт ``text`` админам во все настроенные каналы.

    :param buttons: список ``(label, url)``; каждая кнопка занимает свой ряд.
    :param city_id: город события. Уведомление получат подписчики сети и
        подписчики этого города (франшизы); без города — только подписчики
        сети. Правило одинаковое в обоих каналах.
    :param photos: фото с диска. Нечитаемые файлы, файлы больше 10 МБ и
        всё сверх 40 МБ на уведомление пропускаются; если не прочиталось
        ни одного, уходит обычное текстовое уведомление.
    :return: суммарное число доставок по всем каналам. ``0`` означает, что
        уведомление не ушло никуда — вызывающий код может это залогировать.
    """

    prepared = tuple(buttons)
    loaded = tuple(await _load_photos(tuple(photos)))
    telegram_result, max_result = await asyncio.gather(
        _notify_telegram(text, buttons=prepared, city_id=city_id, photos=loaded),
        _notify_max(text, buttons=prepared, city_id=city_id, photos=loaded),
        return_exceptions=True,
    )
    return _delivered(telegram_result, "telegram") + _delivered(max_result, "max")


def fire_and_forget_notify(
    text: str,
    *,
    buttons: Iterable[InlineButton] = (),
    city_id: UUID | None = None,
    photos: Sequence[NotificationPhoto] = (),
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

    task = loop.create_task(
        notify_admins(
            text,
            buttons=tuple(buttons),
            city_id=city_id,
            photos=tuple(photos),
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


__all__ = [
    "InlineButton",
    "NotificationPhoto",
    "escape_html",
    "fire_and_forget_notify",
    "notify_admins",
]
