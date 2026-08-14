"""Юнит-тесты диспетчера админских уведомлений.

Главное, что здесь проверяется: одно уведомление уходит сразу в оба
канала (Telegram и MAX), а падение одного канала не отменяет второй.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.utils.admin_notifications import notify_admins


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


if __name__ == "__main__":
    unittest.main()
