"""Юнит-тесты диспетчера админских уведомлений.

Главное, что здесь проверяется: одно уведомление уходит сразу в оба
канала (Telegram и MAX), а падение одного канала не отменяет второй.
Фото с диска читаются один раз и одни и те же байты уходят в оба канала;
слишком большие фото пропускаются, не читаясь, а общий объём ограничен.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend.utils import admin_notifications
from backend.utils.admin_notifications import (
    NotificationPhoto,
    fire_and_forget_notify,
    notify_admins,
)


class AdminNotificationsFanOutTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_to_both_channels_and_sums_deliveries(self) -> None:
        telegram = AsyncMock(return_value=2)
        max_channel = AsyncMock(return_value=1)

        with patch(
            "backend.utils.admin_notifications._notify_telegram", telegram
        ), patch("backend.utils.admin_notifications._notify_max", max_channel):
            delivered = await notify_admins(
                "<b>Заявка</b>", buttons=[("Открыть", "https://example.com")]
            )

        self.assertEqual(delivered, 3)
        telegram.assert_awaited_once()
        max_channel.assert_awaited_once()

        # Текст и кнопки одинаковые в обоих каналах — сообщение пишется один раз.
        self.assertEqual(telegram.await_args.args, ("<b>Заявка</b>",))
        self.assertEqual(max_channel.await_args.args, ("<b>Заявка</b>",))
        self.assertEqual(
            telegram.await_args.kwargs["buttons"],
            (("Открыть", "https://example.com"),),
        )
        self.assertEqual(
            max_channel.await_args.kwargs["buttons"],
            (("Открыть", "https://example.com"),),
        )

    async def test_failing_channel_does_not_break_the_other(self) -> None:
        telegram = AsyncMock(side_effect=RuntimeError("telegram is down"))
        max_channel = AsyncMock(return_value=1)

        with patch(
            "backend.utils.admin_notifications._notify_telegram", telegram
        ), patch("backend.utils.admin_notifications._notify_max", max_channel):
            delivered = await notify_admins("hello")

        self.assertEqual(delivered, 1)
        max_channel.assert_awaited_once()

    async def test_returns_zero_when_nothing_configured(self) -> None:
        with patch(
            "backend.utils.admin_notifications._notify_telegram",
            AsyncMock(return_value=0),
        ), patch(
            "backend.utils.admin_notifications._notify_max", AsyncMock(return_value=0)
        ):
            self.assertEqual(await notify_admins("hello"), 0)

    async def test_without_photos_channels_get_empty_photos(self) -> None:
        telegram = AsyncMock(return_value=1)
        max_channel = AsyncMock(return_value=1)

        with patch(
            "backend.utils.admin_notifications._notify_telegram", telegram
        ), patch("backend.utils.admin_notifications._notify_max", max_channel):
            await notify_admins("hello", city_id=None)

        self.assertEqual(telegram.await_args.kwargs["photos"], ())
        self.assertEqual(max_channel.await_args.kwargs["photos"], ())


class AdminNotificationsPhotoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _photo(self, name: str, content: bytes, mime: str = "image/jpeg") -> NotificationPhoto:
        path = self.root / name
        path.write_bytes(content)
        return NotificationPhoto(filename=name, mime_type=mime, path=path)

    async def test_photos_are_read_once_and_passed_to_both_channels(self) -> None:
        telegram = AsyncMock(return_value=1)
        max_channel = AsyncMock(return_value=1)
        photos = [
            self._photo("front.jpg", b"front-bytes"),
            self._photo("side.png", b"side-bytes", "image/png"),
        ]
        real_to_thread = asyncio.to_thread
        to_thread = AsyncMock(side_effect=real_to_thread)

        with patch(
            "backend.utils.admin_notifications._notify_telegram", telegram
        ), patch("backend.utils.admin_notifications._notify_max", max_channel), patch.object(
            admin_notifications.asyncio, "to_thread", to_thread
        ):
            delivered = await notify_admins(
                "<b>Возврат</b>",
                buttons=[("Проверить возврат", "https://admin.test/")],
                photos=photos,
            )

        self.assertEqual(delivered, 2)
        # Диск читается один раз и не в event loop — через to_thread.
        to_thread.assert_awaited_once()

        expected = (
            ("front.jpg", b"front-bytes", "image/jpeg"),
            ("side.png", b"side-bytes", "image/png"),
        )
        self.assertEqual(telegram.await_args.kwargs["photos"], expected)
        self.assertEqual(max_channel.await_args.kwargs["photos"], expected)
        self.assertEqual(telegram.await_args.args, ("<b>Возврат</b>",))
        self.assertEqual(
            max_channel.await_args.kwargs["buttons"],
            (("Проверить возврат", "https://admin.test/"),),
        )

    async def test_unreadable_photo_is_skipped_and_text_still_goes(self) -> None:
        telegram = AsyncMock(return_value=1)
        max_channel = AsyncMock(return_value=1)
        missing = NotificationPhoto(
            filename="gone.jpg", mime_type="image/jpeg", path=self.root / "gone.jpg"
        )
        empty = self._photo("empty.jpg", b"")
        present = self._photo("ok.jpg", b"ok-bytes")

        with patch(
            "backend.utils.admin_notifications._notify_telegram", telegram
        ), patch("backend.utils.admin_notifications._notify_max", max_channel):
            delivered = await notify_admins("hello", photos=[missing, empty, present])

        self.assertEqual(delivered, 2)
        self.assertEqual(
            telegram.await_args.kwargs["photos"], (("ok.jpg", b"ok-bytes", "image/jpeg"),)
        )
        self.assertEqual(
            max_channel.await_args.kwargs["photos"], (("ok.jpg", b"ok-bytes", "image/jpeg"),)
        )

    async def test_oversized_photo_is_skipped_without_reading(self) -> None:
        telegram = AsyncMock(return_value=1)
        max_channel = AsyncMock(return_value=1)
        huge_path = Mock(spec=Path)
        huge_path.stat.return_value = SimpleNamespace(
            st_size=admin_notifications._PHOTO_MAX_BYTES + 1
        )
        huge_path.open.side_effect = AssertionError("oversized photo must not be opened")
        huge_path.read_bytes.side_effect = AssertionError("oversized photo must not be read")
        huge = NotificationPhoto(filename="huge.jpg", mime_type="image/jpeg", path=huge_path)
        present = self._photo("ok.jpg", b"ok-bytes")

        with patch(
            "backend.utils.admin_notifications._notify_telegram", telegram
        ), patch("backend.utils.admin_notifications._notify_max", max_channel):
            delivered = await notify_admins("hello", photos=[huge, present])

        self.assertEqual(delivered, 2)
        self.assertEqual(
            telegram.await_args.kwargs["photos"], (("ok.jpg", b"ok-bytes", "image/jpeg"),)
        )
        self.assertEqual(
            max_channel.await_args.kwargs["photos"], (("ok.jpg", b"ok-bytes", "image/jpeg"),)
        )

    async def test_photo_at_the_limit_is_kept(self) -> None:
        telegram = AsyncMock(return_value=1)
        photo = self._photo("edge.jpg", b"12345678")

        with patch.object(admin_notifications, "_PHOTO_MAX_BYTES", 8), patch(
            "backend.utils.admin_notifications._notify_telegram", telegram
        ), patch(
            "backend.utils.admin_notifications._notify_max", AsyncMock(return_value=0)
        ):
            await notify_admins("hello", photos=[photo])

        self.assertEqual(
            telegram.await_args.kwargs["photos"], (("edge.jpg", b"12345678", "image/jpeg"),)
        )

    async def test_total_bytes_per_notification_are_capped(self) -> None:
        telegram = AsyncMock(return_value=1)
        photos = [
            self._photo("one.jpg", b"11111"),
            self._photo("two.jpg", b"22222"),
            self._photo("three.jpg", b"33333"),
            self._photo("tiny.jpg", b"4"),
        ]

        with patch.object(admin_notifications, "_PHOTO_MAX_BYTES", 8), patch.object(
            admin_notifications, "_PHOTOS_TOTAL_MAX_BYTES", 11
        ), patch("backend.utils.admin_notifications._notify_telegram", telegram), patch(
            "backend.utils.admin_notifications._notify_max", AsyncMock(return_value=0)
        ):
            await notify_admins("hello", photos=photos)

        # Третье фото уже не влезает в общий лимит, маленькое после него — влезает.
        self.assertEqual(
            [name for name, _, _ in telegram.await_args.kwargs["photos"]],
            ["one.jpg", "two.jpg", "tiny.jpg"],
        )

    async def test_photo_that_grew_after_stat_is_skipped(self) -> None:
        telegram = AsyncMock(return_value=1)
        path = self.root / "growing.jpg"
        path.write_bytes(b"0123456789abcdef")
        growing_path = Mock(spec=Path)
        growing_path.stat.return_value = SimpleNamespace(st_size=4)
        growing_path.open.side_effect = lambda mode: path.open(mode)
        growing = NotificationPhoto(
            filename="growing.jpg", mime_type="image/jpeg", path=growing_path
        )

        with patch.object(admin_notifications, "_PHOTO_MAX_BYTES", 8), patch(
            "backend.utils.admin_notifications._notify_telegram", telegram
        ), patch(
            "backend.utils.admin_notifications._notify_max", AsyncMock(return_value=0)
        ):
            await notify_admins("hello", photos=[growing])

        self.assertEqual(telegram.await_args.kwargs["photos"], ())

    async def test_fire_and_forget_keeps_strong_reference_until_done(self) -> None:
        release = asyncio.Event()
        received: dict = {}

        async def slow_notify(text, **kwargs):
            received.update(kwargs, text=text)
            await release.wait()
            return 1

        photo = self._photo("front.jpg", b"front-bytes")
        with patch.object(admin_notifications, "notify_admins", slow_notify):
            fire_and_forget_notify(
                "hello",
                buttons=[("Проверить возврат", "https://admin.test/")],
                photos=[photo],
            )
            tasks = set(admin_notifications._background_tasks)
            self.assertEqual(len(tasks), 1)

            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(*tasks)
            await asyncio.sleep(0)

        self.assertEqual(admin_notifications._background_tasks, set())
        self.assertEqual(received["text"], "hello")
        self.assertEqual(received["photos"], (photo,))
        self.assertEqual(
            received["buttons"], (("Проверить возврат", "https://admin.test/"),)
        )


class FireAndForgetWithoutLoopTests(unittest.TestCase):
    def test_no_running_loop_is_a_noop(self) -> None:
        fire_and_forget_notify("hello", photos=())
        self.assertEqual(admin_notifications._background_tasks, set())


if __name__ == "__main__":
    unittest.main()
