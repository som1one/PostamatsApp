"""Общий цикл фоновых планировщиков.

Каждый планировщик (просрочки, истечение броней, автовыдача, сверка ESI и
т. д.) — это поток, который раз в N секунд гонит корутину в главном event
loop. Раньше цикл был обёрнут в один общий ``try``: первая же ошибка
прохода (база на секунду не ответила, сеть моргнула) роняла поток, в лог
уходило «scheduler stopped unexpectedly», и до перезапуска бэкенда
планировщик больше не работал. Так, например, тихо переставали уходить
уведомления о просрочке аренды.

Здесь ошибка одного прохода только логируется, а следующий проход
случается не позже чем через :data:`FAILURE_RETRY_SECONDS` — даже если
обычный интервал больше (у ротации товара дня он до суток).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, Callable, Union

logger = logging.getLogger(__name__)

# Через сколько секунд повторить проход, который упал. Обычный интервал
# может быть меньше — тогда берётся он.
FAILURE_RETRY_SECONDS = 60.0

Interval = Union[float, Callable[[], float]]


def _resolve_interval(interval: Interval) -> float:
    value = interval() if callable(interval) else interval
    return max(0.0, float(value))


def run_scheduler_loop(
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
    tick: Callable[[], Awaitable[object]],
    interval: Interval,
    *,
    name: str,
) -> None:
    """Гоняет ``tick()`` в ``loop``, пока не выставлен ``stop_event``.

    Первый проход — сразу, дальше — через ``interval`` секунд (число или
    функция, которая его считает). Исключение из прохода не останавливает
    цикл. Цикл заканчивается по ``stop_event`` или если ``loop`` закрыт.
    """

    while not stop_event.is_set():
        if loop.is_closed():
            logger.warning("%s scheduler: event loop is closed, stopping", name)
            return

        failed = False
        try:
            asyncio.run_coroutine_threadsafe(tick(), loop).result()
        except Exception:
            failed = True
            logger.exception("%s scheduler tick failed, will retry", name)

        try:
            delay = _resolve_interval(interval)
        except Exception:
            logger.exception("%s scheduler: failed to compute the next interval", name)
            delay = FAILURE_RETRY_SECONDS
        if failed:
            delay = min(delay, FAILURE_RETRY_SECONDS)

        if stop_event.wait(delay):
            return
