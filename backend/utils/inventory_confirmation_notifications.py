"""Уведомления операторам о вещи, возвращённой в постамат.

Возврат завершается одним из трёх путей (кнопка клиента, вебхук дверцы,
reconcile), и после commit операторы получают «товар ожидает
подтверждения». Если клиент приложил фото возврата, они уходят вместе с
этим сообщением; если фото пришли позже (дверца закрылась раньше кнопки) —
отдельным сообщением «Фото возврата», а если клиент дослал только
комментарий — сообщением «Комментарий к возврату».
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath
from urllib.parse import urlencode

from backend.core.exceptions import ClientError
from backend.core.settings import settings
from backend.models.inventory_unit import InventoryUnit
from backend.models.media_file import MediaFile
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.rental import Rental
from backend.utils.admin_links import build_admin_rentals_url
from backend.utils.admin_notifications import (
    NotificationPhoto,
    escape_html,
    fire_and_forget_notify,
)
from backend.utils.local_storage import local_upload_path
from backend.utils.telegram_bot import TELEGRAM_CAPTION_LIMIT, telegram_text_length

# Лимит текста сообщения без фото: у MAX он 4000, у Telegram — 4096.
_MESSAGE_TEXT_LIMIT = 4000

# Меньше этого комментарий не режем: лучше длинный текст уйдёт отдельным
# сообщением после фото, чем от комментария останется пара слов.
_NOTE_MIN_LENGTH = 80

_NOTE_PREFIX = "💬 "
_ELLIPSIS = "…"


def _build_inventory_admin_link(locker_id, cell_id) -> str | None:
    base = settings.ADMIN_PANEL_URL
    if not base:
        return None
    query = urlencode(
        {
            "section": "inventory",
            "locker": str(locker_id),
            "cell": str(cell_id),
        }
    )
    return f"{base.rstrip('/')}/?{query}"


def _build_buttons(
    *, rental: Rental, locker: LockerLocation, cell: LockerCell
) -> list[tuple[str, str]]:
    buttons: list[tuple[str, str]] = []
    rental_link = build_admin_rentals_url(rental.id)
    if rental_link:
        buttons.append(("Проверить возврат", rental_link))
    inventory_link = _build_inventory_admin_link(locker.id, cell.id)
    if inventory_link:
        buttons.append(("Ячейка в админке", inventory_link))
    return buttons


def _photo_filename(media: MediaFile) -> str:
    for candidate in (media.original_name, media.file_key):
        # Имя присылает клиент — от пути оставляем только последний сегмент.
        name = PurePosixPath((candidate or "").replace("\\", "/")).name.strip()
        if name:
            return name
    return f"{media.id}.jpg"


def notification_photos_from_media(files: Sequence[MediaFile]) -> list[NotificationPhoto]:
    """Фото возврата, которые реально можно отправить в мессенджер.

    Байты есть только у ``filesystem``-хранилища: stub (dev/тесты) файлов
    не хранит, а скачивания из s3 у нас нет. Такие файлы и файлы,
    пропавшие с диска, просто пропускаем — уведомление уйдёт без них.
    """

    photos: list[NotificationPhoto] = []
    for media in files:
        if media.storage_provider != "filesystem":
            continue
        try:
            path = local_upload_path(media.file_key)
        except ClientError:
            continue
        if not path.is_file():
            continue
        photos.append(
            NotificationPhoto(
                filename=_photo_filename(media),
                mime_type=media.mime_type or "image/jpeg",
                path=path,
            )
        )
    return photos


def _note_line(note: str | None, *, budget: int) -> str | None:
    """Строка с комментарием клиента, ужатая до ``budget`` символов.

    Режем сырой текст, а не экранированный, чтобы не разрезать HTML-сущность
    посередине.
    """

    cleaned = (note or "").strip()
    if not cleaned:
        return None
    line = _NOTE_PREFIX + escape_html(cleaned)
    if telegram_text_length(line) <= budget:
        return line

    def fits(length: int) -> bool:
        candidate = _NOTE_PREFIX + escape_html(cleaned[:length].rstrip()) + _ELLIPSIS
        return telegram_text_length(candidate) <= budget

    low, high = 0, len(cleaned)
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    return _NOTE_PREFIX + escape_html(cleaned[:low].rstrip()) + _ELLIPSIS


def _send(
    lines: list[str],
    *,
    note: str | None,
    return_photos: Sequence[MediaFile] | None,
    locker: LockerLocation,
    cell: LockerCell,
    rental: Rental,
) -> None:
    photos = notification_photos_from_media(return_photos or ())
    # С фото текст уходит подписью, а у неё в Telegram лимит 1024 символа.
    limit = TELEGRAM_CAPTION_LIMIT if photos else _MESSAGE_TEXT_LIMIT
    base_length = telegram_text_length("\n".join(lines))
    budget = max(limit - base_length - 1, _NOTE_MIN_LENGTH)
    note_line = _note_line(note, budget=budget)
    if note_line:
        lines.append(note_line)

    fire_and_forget_notify(
        "\n".join(lines),
        buttons=_build_buttons(rental=rental, locker=locker, cell=cell),
        city_id=locker.city_id,
        photos=photos,
    )


def _no_photos_line() -> str:
    """Предупреждение о возврате без фото.

    Это ещё не «клиент фото не приложил»: после завершения возврата он может
    дослать их в течение ``RETURN_PHOTO_LATE_WINDOW_MINUTES``.
    """

    window = getattr(settings, "RETURN_PHOTO_LATE_WINDOW_MINUTES", 0) or 0
    if window > 0:
        return f"⚠️ Возврат без фото — клиент может дослать в течение {window} мин"
    return "⚠️ Возврат без фото"


def _location_lines(
    *, locker: LockerLocation, cell: LockerCell, unit: InventoryUnit, rental: Rental
) -> list[str]:
    cell_label = (cell.label or cell.external_cell_id or str(cell.id)).strip()
    serial_label = unit.serial_number or unit.barcode or str(unit.id)
    return [
        f"📍 {escape_html(locker.name)} · ячейка {escape_html(cell_label)}",
        f"🔖 {escape_html(serial_label)}",
        f"🧾 Аренда {escape_html(str(rental.id))}",
    ]


def notify_return_photos_attached(
    *,
    product: Product,
    locker: LockerLocation,
    cell: LockerCell,
    unit: InventoryUnit,
    rental: Rental,
    return_photos: Sequence[MediaFile],
    note: str | None = None,
) -> None:
    """Досланное клиентом после того, как возврат завершила дверца.

    С фото — «Фото возврата» (и комментарий, если есть). Без фото, но с
    комментарием — «Комментарий к возврату»: фото клиент, возможно, ещё
    дошлёт, поэтому предупреждения «возврат без фото» здесь нет. Без фото и
    без комментария операторам показывать нечего — ничего не шлём.
    """

    product_name = escape_html(product.name)
    if return_photos:
        title = f"📷 <b>Фото возврата · {product_name}</b>"
    elif (note or "").strip():
        title = f"💬 <b>Комментарий к возврату · {product_name}</b>"
    else:
        return

    lines = [
        title,
        *_location_lines(locker=locker, cell=cell, unit=unit, rental=rental),
    ]

    _send(
        lines,
        note=note,
        return_photos=return_photos,
        locker=locker,
        cell=cell,
        rental=rental,
    )


def notify_inventory_awaiting_confirmation(
    *,
    product: Product,
    locker: LockerLocation,
    cell: LockerCell,
    unit: InventoryUnit,
    rental: Rental,
    return_photos: Sequence[MediaFile] | None = None,
    note: str | None = None,
) -> None:
    """Вещь вернулась в ячейку и ждёт проверки оператором.

    ``return_photos``: ``None`` — про фото ещё ничего не известно (вебхук,
    reconcile), строки о фото нет; ``[]`` — клиент подтвердил возврат без
    фото (и ещё может их дослать); список файлов — фото уходят вместе с
    сообщением.
    """

    lines = [
        f"⏳ <b>Товар {escape_html(product.name)} ожидает подтверждения</b>",
        *_location_lines(locker=locker, cell=cell, unit=unit, rental=rental),
    ]
    if return_photos is not None:
        if return_photos:
            lines.append(f"📷 Фото: {len(return_photos)}")
        else:
            lines.append(_no_photos_line())

    _send(
        lines,
        note=note,
        return_photos=return_photos,
        locker=locker,
        cell=cell,
        rental=rental,
    )
