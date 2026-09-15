"""Юнит-тесты уведомлений о вещи, возвращённой в постамат.

Проверяем тексты и кнопки для трёх состояний фото возврата (неизвестно,
без фото — с окном дослать, приложил), досланные фото и досланный без фото
комментарий, экранирование комментария клиента, лимит подписи Telegram и
отбор файлов, которые реально можно отправить.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from backend.core.settings import settings
from backend.models.enums import MediaFileKind
from backend.models.media_file import MediaFile
from backend.utils.admin_notifications import NotificationPhoto
from backend.utils.inventory_confirmation_notifications import (
    notification_photos_from_media,
    notify_inventory_awaiting_confirmation,
    notify_return_photos_attached,
)
from backend.utils.telegram_bot import TELEGRAM_CAPTION_LIMIT, telegram_text_length

_MODULE = "backend.utils.inventory_confirmation_notifications"

_LOCKER_ID = UUID("11111111-1111-1111-1111-111111111111")
_CELL_ID = UUID("22222222-2222-2222-2222-222222222222")
_CITY_ID = UUID("33333333-3333-3333-3333-333333333333")
_RENTAL_ID = UUID("44444444-4444-4444-4444-444444444444")


def _entities() -> dict:
    return {
        "product": SimpleNamespace(name="Пылесос <Pro>"),
        "locker": SimpleNamespace(id=_LOCKER_ID, name="ТЦ «Мега»", city_id=_CITY_ID),
        "cell": SimpleNamespace(id=_CELL_ID, label="A3", external_cell_id="7"),
        "unit": SimpleNamespace(id=uuid4(), serial_number="SN-1", barcode=None),
        "rental": SimpleNamespace(id=_RENTAL_ID),
    }


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._old_admin_url = settings.ADMIN_PANEL_URL
        self._old_root = settings.LOCAL_UPLOAD_ROOT
        self._tmp = tempfile.TemporaryDirectory()
        settings.LOCAL_UPLOAD_ROOT = self._tmp.name
        settings.ADMIN_PANEL_URL = "https://admin.test/"

    def tearDown(self) -> None:
        settings.ADMIN_PANEL_URL = self._old_admin_url
        settings.LOCAL_UPLOAD_ROOT = self._old_root
        self._tmp.cleanup()

    def _media(
        self,
        key: str,
        *,
        provider: str = "filesystem",
        original_name: str | None = None,
        write: bytes | None = b"jpeg",
        mime_type: str = "image/jpeg",
    ) -> MediaFile:
        if write is not None and provider == "filesystem":
            path = Path(self._tmp.name) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(write)
        return MediaFile(
            id=uuid4(),
            storage_provider=provider,
            bucket="local",
            file_key=key,
            mime_type=mime_type,
            file_size=len(write or b""),
            original_name=original_name,
            kind=MediaFileKind.CONDITION_PHOTO_AFTER,
            created_at=datetime.now(timezone.utc),
        )

    def _call(self, func, **kwargs) -> Mock:
        notify = Mock()
        with patch(f"{_MODULE}.fire_and_forget_notify", notify):
            func(**_entities(), **kwargs)
        notify.assert_called_once()
        return notify


_EXPECTED_BUTTONS = [
    ("Проверить возврат", f"https://admin.test/?section=rentals&rental={_RENTAL_ID}"),
    (
        "Ячейка в админке",
        f"https://admin.test/?section=inventory&locker={_LOCKER_ID}&cell={_CELL_ID}",
    ),
]

_BASE_LINES = [
    "⏳ <b>Товар Пылесос &lt;Pro&gt; ожидает подтверждения</b>",
    "📍 ТЦ «Мега» · ячейка A3",
    "🔖 SN-1",
    f"🧾 Аренда {_RENTAL_ID}",
]


class AwaitingConfirmationTests(_Base):
    def test_unknown_photos_keep_old_text_with_new_buttons(self) -> None:
        notify = self._call(notify_inventory_awaiting_confirmation)

        self.assertEqual(notify.call_args.args, ("\n".join(_BASE_LINES),))
        self.assertEqual(notify.call_args.kwargs["buttons"], _EXPECTED_BUTTONS)
        self.assertEqual(notify.call_args.kwargs["city_id"], _CITY_ID)
        self.assertEqual(notify.call_args.kwargs["photos"], [])

    def test_empty_photos_warn_that_client_can_still_send_them(self) -> None:
        with patch.object(settings, "RETURN_PHOTO_LATE_WINDOW_MINUTES", 45):
            notify = self._call(notify_inventory_awaiting_confirmation, return_photos=[])

        # Фото ещё могут прийти в окне дослать — «не приложил» было бы неправдой.
        self.assertEqual(
            notify.call_args.args[0],
            "\n".join(
                [*_BASE_LINES, "⚠️ Возврат без фото — клиент может дослать в течение 45 мин"]
            ),
        )
        self.assertNotIn("не приложил", notify.call_args.args[0])
        self.assertEqual(notify.call_args.kwargs["photos"], [])

    def test_empty_photos_without_late_window_is_plain_warning(self) -> None:
        for window in (0, None):
            with self.subTest(window=window), patch.object(
                settings, "RETURN_PHOTO_LATE_WINDOW_MINUTES", window
            ):
                notify = self._call(
                    notify_inventory_awaiting_confirmation, return_photos=[]
                )

                self.assertEqual(
                    notify.call_args.args[0],
                    "\n".join([*_BASE_LINES, "⚠️ Возврат без фото"]),
                )

    def test_photos_are_counted_and_attached(self) -> None:
        files = [
            self._media("condition/a.jpg", original_name="front.jpg"),
            self._media("condition/b.png", mime_type="image/png"),
        ]

        notify = self._call(notify_inventory_awaiting_confirmation, return_photos=files)

        text = notify.call_args.args[0]
        self.assertEqual(text, "\n".join([*_BASE_LINES, "📷 Фото: 2"]))
        self.assertNotIn("Возврат без фото", text)
        root = Path(self._tmp.name).resolve()
        self.assertEqual(
            notify.call_args.kwargs["photos"],
            [
                NotificationPhoto("front.jpg", "image/jpeg", root / "condition" / "a.jpg"),
                NotificationPhoto("b.png", "image/png", root / "condition" / "b.png"),
            ],
        )
        self.assertEqual(notify.call_args.kwargs["buttons"], _EXPECTED_BUTTONS)

    def test_photo_count_uses_attached_files_even_without_bytes(self) -> None:
        # dev/stub: байтов нет, но клиент фото приложил — строка остаётся.
        files = [self._media("condition/stub.jpg", provider="stub")]

        notify = self._call(notify_inventory_awaiting_confirmation, return_photos=files)

        self.assertIn("📷 Фото: 1", notify.call_args.args[0])
        self.assertEqual(notify.call_args.kwargs["photos"], [])

    def test_note_is_escaped(self) -> None:
        with patch.object(settings, "RETURN_PHOTO_LATE_WINDOW_MINUTES", 120):
            notify = self._call(
                notify_inventory_awaiting_confirmation,
                return_photos=[],
                note="  <b>Сломан</b> & «ok»\n",
            )

        lines = notify.call_args.args[0].split("\n")
        self.assertEqual(lines[-1], "💬 &lt;b&gt;Сломан&lt;/b&gt; &amp; «ok»")
        self.assertEqual(
            lines[-2], "⚠️ Возврат без фото — клиент может дослать в течение 120 мин"
        )

    def test_blank_note_adds_no_line(self) -> None:
        notify = self._call(
            notify_inventory_awaiting_confirmation, return_photos=[], note="   "
        )

        self.assertNotIn("💬", notify.call_args.args[0])

    def test_long_note_is_cut_to_fit_photo_caption(self) -> None:
        files = [self._media("condition/a.jpg")]
        note = "&" * 500 + "конец"

        notify = self._call(
            notify_inventory_awaiting_confirmation, return_photos=files, note=note
        )

        text = notify.call_args.args[0]
        self.assertLessEqual(telegram_text_length(text), TELEGRAM_CAPTION_LIMIT)
        note_line = text.split("\n")[-1]
        self.assertTrue(note_line.startswith("💬 &amp;"))
        self.assertTrue(note_line.endswith("&amp;…"))
        self.assertNotIn("конец", text)
        self.assertEqual(len(notify.call_args.kwargs["photos"]), 1)

    def test_long_note_is_kept_when_there_is_no_photo_caption(self) -> None:
        note = "&" * 500

        notify = self._call(
            notify_inventory_awaiting_confirmation, return_photos=[], note=note
        )

        self.assertEqual(notify.call_args.args[0].split("\n")[-1], "💬 " + "&amp;" * 500)

    def test_no_admin_url_means_no_buttons(self) -> None:
        settings.ADMIN_PANEL_URL = None

        notify = self._call(notify_inventory_awaiting_confirmation)

        self.assertEqual(notify.call_args.kwargs["buttons"], [])


class ReturnPhotosAttachedTests(_Base):
    def test_late_photos_message(self) -> None:
        files = [self._media("condition/a.jpg"), self._media("condition/b.jpg")]

        notify = self._call(
            notify_return_photos_attached, return_photos=files, note="Царапина <сбоку>"
        )

        self.assertEqual(
            notify.call_args.args[0],
            "\n".join(
                [
                    "📷 <b>Фото возврата · Пылесос &lt;Pro&gt;</b>",
                    "📍 ТЦ «Мега» · ячейка A3",
                    "🔖 SN-1",
                    f"🧾 Аренда {_RENTAL_ID}",
                    "💬 Царапина &lt;сбоку&gt;",
                ]
            ),
        )
        self.assertEqual(len(notify.call_args.kwargs["photos"]), 2)
        self.assertEqual(notify.call_args.kwargs["buttons"], _EXPECTED_BUTTONS)
        self.assertEqual(notify.call_args.kwargs["city_id"], _CITY_ID)

    def test_late_photos_without_note(self) -> None:
        files = [self._media("condition/a.jpg")]

        notify = self._call(notify_return_photos_attached, return_photos=files, note=None)

        text = notify.call_args.args[0]
        self.assertTrue(text.startswith("📷 <b>Фото возврата · Пылесос &lt;Pro&gt;</b>\n"))
        self.assertNotIn("💬", text)
        self.assertNotIn("Возврат без фото", text)
        self.assertEqual(len(notify.call_args.kwargs["photos"]), 1)

    def test_late_note_without_photos_is_a_comment_message(self) -> None:
        notify = self._call(
            notify_return_photos_attached,
            return_photos=[],
            note="  Дверца не закрывается & царапина <сбоку>\n",
        )

        self.assertEqual(
            notify.call_args.args[0],
            "\n".join(
                [
                    "💬 <b>Комментарий к возврату · Пылесос &lt;Pro&gt;</b>",
                    "📍 ТЦ «Мега» · ячейка A3",
                    "🔖 SN-1",
                    f"🧾 Аренда {_RENTAL_ID}",
                    "💬 Дверца не закрывается &amp; царапина &lt;сбоку&gt;",
                ]
            ),
        )
        # Фото клиент ещё может дослать — предупреждения «без фото» нет.
        self.assertNotIn("Возврат без фото", notify.call_args.args[0])
        self.assertEqual(notify.call_args.kwargs["photos"], [])
        self.assertEqual(notify.call_args.kwargs["buttons"], _EXPECTED_BUTTONS)
        self.assertEqual(notify.call_args.kwargs["city_id"], _CITY_ID)

    def test_long_late_note_without_photos_is_not_cut_to_caption(self) -> None:
        note = "&" * 500

        notify = self._call(notify_return_photos_attached, return_photos=[], note=note)

        self.assertEqual(notify.call_args.args[0].split("\n")[-1], "💬 " + "&amp;" * 500)

    def test_nothing_to_report_sends_nothing(self) -> None:
        notify = Mock()
        with patch(f"{_MODULE}.fire_and_forget_notify", notify):
            notify_return_photos_attached(**_entities(), return_photos=[], note="   ")
            notify_return_photos_attached(**_entities(), return_photos=[], note=None)

        notify.assert_not_called()


class NotificationPhotosFromMediaTests(_Base):
    def test_only_existing_filesystem_files_are_kept(self) -> None:
        present = self._media("condition/present.jpg")
        missing = self._media("condition/missing.jpg", write=None)
        stub = self._media("condition/stub.jpg", provider="stub")
        s3 = self._media("condition/s3.jpg", provider="s3")
        escaping = self._media("../outside.jpg", write=None)

        photos = notification_photos_from_media([stub, missing, present, s3, escaping])

        self.assertEqual(
            photos,
            [
                NotificationPhoto(
                    "present.jpg",
                    "image/jpeg",
                    Path(self._tmp.name).resolve() / "condition" / "present.jpg",
                )
            ],
        )

    def test_filename_comes_from_original_name_or_key(self) -> None:
        named = self._media("condition/uuid-1.jpg", original_name="C:\\Users\\me\\IMG_1.jpg")
        unnamed = self._media("condition/uuid-2.jpg", original_name="  ")

        photos = notification_photos_from_media([named, unnamed])

        self.assertEqual([photo.filename for photo in photos], ["IMG_1.jpg", "uuid-2.jpg"])

    def test_directory_with_file_key_is_not_a_photo(self) -> None:
        media = self._media("condition/folder", write=None)
        (Path(self._tmp.name) / "condition" / "folder").mkdir(parents=True)

        self.assertEqual(notification_photos_from_media([media]), [])


if __name__ == "__main__":
    unittest.main()
