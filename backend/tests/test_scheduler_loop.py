from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import patch

from backend.utils import scheduler_loop
from backend.utils.scheduler_loop import run_scheduler_loop


class _LoopThread:
    """Event loop в отдельном потоке — как главный loop бэкенда для воркера."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def __enter__(self) -> asyncio.AbstractEventLoop:
        self.thread.start()
        return self.loop

    def __exit__(self, *exc) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


def _start_worker(loop, stop_event, tick, interval):
    worker = threading.Thread(
        target=run_scheduler_loop,
        args=(loop, stop_event, tick, interval),
        kwargs={"name": "Test"},
        daemon=True,
    )
    worker.start()
    return worker


class SchedulerLoopTest(unittest.TestCase):
    def test_failed_tick_does_not_stop_the_scheduler(self) -> None:
        # Раньше первая же ошибка прохода роняла поток насовсем — так тихо
        # переставали уходить уведомления о просрочке аренды.
        calls = 0
        recovered = threading.Event()
        stop_event = threading.Event()

        async def tick() -> None:
            nonlocal calls
            calls += 1
            if calls <= 2:
                raise RuntimeError("database is unavailable")
            recovered.set()

        with _LoopThread() as loop:
            with self.assertLogs(scheduler_loop.logger, level="ERROR") as logs:
                worker = _start_worker(loop, stop_event, tick, 0.01)
                self.assertTrue(recovered.wait(5), "scheduler stopped after a failed tick")
                stop_event.set()
                worker.join(5)

        self.assertFalse(worker.is_alive())
        self.assertGreaterEqual(calls, 3)
        self.assertEqual(
            sum("Test scheduler tick failed" in line for line in logs.output), 2
        )

    def test_failed_tick_retries_sooner_than_a_long_interval(self) -> None:
        # У ротации товара дня интервал до суток: после ошибки ждать его
        # целиком нельзя.
        waits: list[float] = []
        stop_event = threading.Event()
        real_wait = stop_event.wait

        def recording_wait(timeout=None):
            waits.append(timeout)
            return True  # останавливаемся после первого ожидания

        stop_event.wait = recording_wait  # type: ignore[method-assign]

        async def failing_tick() -> None:
            raise RuntimeError("boom")

        with _LoopThread() as loop:
            with patch.object(scheduler_loop, "FAILURE_RETRY_SECONDS", 7.0):
                with self.assertLogs(scheduler_loop.logger, level="ERROR"):
                    run_scheduler_loop(
                        loop, stop_event, failing_tick, lambda: 86400.0, name="Test"
                    )

        stop_event.wait = real_wait  # type: ignore[method-assign]
        self.assertEqual(waits, [7.0])

    def test_successful_tick_waits_the_regular_interval(self) -> None:
        waits: list[float] = []
        stop_event = threading.Event()
        stop_event.wait = lambda timeout=None: waits.append(timeout) or True  # type: ignore[method-assign]

        async def tick() -> None:
            return None

        with _LoopThread() as loop:
            run_scheduler_loop(loop, stop_event, tick, lambda: 120.0, name="Test")

        self.assertEqual(waits, [120.0])

    def test_stops_when_the_event_loop_is_closed(self) -> None:
        loop = asyncio.new_event_loop()
        loop.close()
        calls = 0

        async def tick() -> None:
            nonlocal calls
            calls += 1

        worker = _start_worker(loop, threading.Event(), tick, 0.01)
        worker.join(5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
