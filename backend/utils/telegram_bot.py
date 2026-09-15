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
- К уведомлению можно приложить фото (``photos``). Одно фото уходит
  ``sendPhoto`` с текстом в подписи и кнопками, несколько — альбомом
  ``sendMediaGroup`` и следом обычным сообщением с кнопками (у альбома
  клавиатуры не бывает). Байты грузятся по чатам по очереди, пока
  какой-нибудь чат их не примет; остальным чатам — и тем, у кого раньше
  не вышло, — отправляем уже полученные ``file_id``. Недоступный чат
  (бот заблокирован, чат не найден) попытку не тратит, а после двух
  сбоев не по вине чата (таймаут, 429, 5xx, фото не принято) байты больше
  не грузим: остальные чаты сразу получают текст. Фото, которое
  Telegram не принял как фото (стороны слишком большие, не смог
  обработать), повторяем документом. Если фото так и не ушло, чат всё
  равно получает текст — уведомление важнее картинки. Исключение —
  таймаут, когда запрос уже ушёл: сообщение могло дойти, и повтор
  текстом стал бы дублем, поэтому такой чат больше не трогаем.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
from dataclasses import dataclass
from html import escape as escape_html
from typing import Iterable, Sequence
from uuid import UUID

import httpx

from backend.core.database import SessionLocal
from backend.core.settings import settings

logger = logging.getLogger(__name__)

# Inline keyboard with a single URL button.
InlineButton = tuple[str, str]

# Фото для отправки: (имя файла, байты, MIME) — ровно формат ``files`` у httpx.
PhotoFile = tuple[str, bytes, str]

# Лимит подписи к фото в Telegram. Сообщение длиннее уходит отдельно от фото.
TELEGRAM_CAPTION_LIMIT = 1024

# Больше фото в один альбом Telegram не принимает.
_MEDIA_GROUP_LIMIT = 10

# Загрузка фото заметно дольше обычного sendMessage.
_PHOTO_TIMEOUT_SECONDS = 30.0

# Таймауты, после которых запрос мог дойти до Telegram: тело уже ушло
# (или уходило), просто ответа не дождались. Повторять такое сообщение
# текстом нельзя — оператор получит дубль.
_MAYBE_DELIVERED_ERRORS = (httpx.ReadTimeout, httpx.WriteTimeout)

# Сколько раз загрузка байтов может сорваться не по вине чата (таймаут,
# 429, 5xx, фото не принято и документом), прежде чем мы перестанем
# грузить их в следующие чаты: каждая попытка — до 30 с, и текст ждёт.
_UPLOAD_FAILURE_LIMIT = 2


def telegram_text_length(text: str) -> int:
    """Длина текста так, как её меряет Telegram — в UTF-16 code units.

    Считаем по сырому HTML, поэтому оценка сверху: теги и сущности в
    видимую длину не входят.
    """

    return len(text.encode("utf-16-le")) // 2


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
) -> bool:
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
        return False

    if response.status_code >= 400:
        # 403 — пользователь не нажал /start или заблокировал бота.
        # 400 — кривой chat_id или markdown. Логируем, но не падаем.
        logger.warning(
            "Telegram sendMessage non-2xx for chat %s: %s %s",
            chat_id,
            response.status_code,
            response.text[:200],
        )
        return False

    return True


class _Outcome(enum.Enum):
    SENT = "sent"
    # Telegram ответил ошибкой или запрос не ушёл — можно слать фолбэк.
    FAILED = "failed"
    # Таймаут после отправки: сообщение могло дойти, повторять нельзя.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class _ApiCall:
    outcome: _Outcome
    response: httpx.Response | None = None


@dataclass(frozen=True)
class _Uploaded:
    """Файлы, которые уже лежат в Telegram и уходят по ``file_id``."""

    kind: str  # "photo" или "document"
    file_ids: tuple[str, ...]


@dataclass(frozen=True)
class _MediaResult:
    outcome: _Outcome
    uploaded: _Uploaded | None = None
    # Сбой из-за самого чата (бот заблокирован, чат не найден): другим
    # чатам он ничего не предвещает.
    chat_unreachable: bool = False


def _message_file_id(message: object, kind: str) -> str | None:
    """``file_id`` из отправленного сообщения: у фото — самый крупный размер."""

    if not isinstance(message, dict):
        return None
    if kind == "photo":
        sizes = message.get("photo")
        if not isinstance(sizes, list) or not sizes:
            return None
        item = sizes[-1]
    else:
        item = message.get(kind)
    if not isinstance(item, dict):
        return None
    file_id = item.get("file_id")
    return file_id if isinstance(file_id, str) and file_id else None


def _extract_uploaded(
    response: httpx.Response | None, kind: str, expected: int
) -> _Uploaded | None:
    if response is None:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    messages = result if isinstance(result, list) else [result]
    file_ids = [_message_file_id(message, kind) for message in messages]
    if len(file_ids) != expected or any(item is None for item in file_ids):
        return None
    return _Uploaded(kind, tuple(item for item in file_ids if item is not None))


async def _post_file_method(
    client: httpx.AsyncClient,
    method: str,
    chat_id: str,
    data: dict[str, str],
    files: dict[str, PhotoFile],
) -> _ApiCall:
    try:
        response = await client.post(
            _telegram_api_url(method),
            data=data,
            files=files or None,
        )
    except _MAYBE_DELIVERED_ERRORS:
        logger.warning(
            "Telegram %s timed out for chat %s after the request was sent, "
            "not resending",
            method,
            chat_id,
        )
        return _ApiCall(_Outcome.UNKNOWN)
    except httpx.RequestError:
        logger.exception("Telegram %s failed for chat %s", method, chat_id)
        return _ApiCall(_Outcome.FAILED)

    if response.status_code >= 400:
        logger.warning(
            "Telegram %s non-2xx for chat %s: %s %s",
            method,
            chat_id,
            response.status_code,
            response.text[:200],
        )
        return _ApiCall(_Outcome.FAILED, response)
    return _ApiCall(_Outcome.SENT, response)


async def _send_files(
    client: httpx.AsyncClient,
    chat_id: str,
    kind: str,
    items: Sequence[PhotoFile | str],
    *,
    caption: str | None,
    reply_markup: dict | None,
) -> _ApiCall:
    """Один файл (``sendPhoto``/``sendDocument``) или альбом (``sendMediaGroup``).

    ``items`` — байты для загрузки или уже известные ``file_id``. Подпись и
    кнопки бывают только у одиночного файла: текст к альбому уходит следом
    отдельным сообщением.
    """

    data: dict[str, str] = {"chat_id": chat_id}
    files: dict[str, PhotoFile] = {}

    if len(items) == 1:
        item = items[0]
        if isinstance(item, str):
            data[kind] = item
        else:
            files[kind] = item
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"
        if reply_markup is not None:
            data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        method = "sendPhoto" if kind == "photo" else "sendDocument"
        return await _post_file_method(client, method, chat_id, data, files)

    media: list[dict[str, str]] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            media.append({"type": kind, "media": item})
        else:
            name = f"p{index}"
            files[name] = item
            media.append({"type": kind, "media": f"attach://{name}"})
    data["media"] = json.dumps(media)
    return await _post_file_method(client, "sendMediaGroup", chat_id, data, files)


def _is_chat_unreachable(response: httpx.Response | None) -> bool:
    """Ошибка про сам чат: 403 (бот заблокирован, не запущен, выгнан) или
    400 «chat not found». Следующий чат из-за неё не пострадает."""

    if response is None:
        return False
    if response.status_code == 403:
        return True
    if response.status_code != 400:
        return False
    return "chat not found" in (response.text or "").lower()


def _is_photo_rejected(response: httpx.Response | None) -> bool:
    """Telegram не принял сами фото, а не чат.

    ``PHOTO_INVALID_DIMENSIONS``, ``IMAGE_PROCESS_FAILED``,
    ``PHOTO_SAVE_FILE_INVALID`` и прочие 400 на фото документ обходит: у
    него нет проверки сторон и перекодирования. Несуществующий чат
    документом не починить, лишний раз грузить в него байты незачем.
    """

    if response is None:
        return False
    if response.status_code == 413:
        return True
    if response.status_code != 400:
        return False
    return not _is_chat_unreachable(response)


async def _send_media(
    client: httpx.AsyncClient,
    chat_id: str,
    media: Sequence[PhotoFile] | _Uploaded,
    *,
    caption: str | None,
    reply_markup: dict | None,
) -> _MediaResult:
    """Фото в один чат — байтами или по ``file_id``. Текст — только в подписи."""

    try:
        if isinstance(media, _Uploaded):
            call = await _send_files(
                client,
                chat_id,
                media.kind,
                media.file_ids,
                caption=caption,
                reply_markup=reply_markup,
            )
            uploaded = media if call.outcome is _Outcome.SENT else None
            return _MediaResult(call.outcome, uploaded)

        kind = "photo"
        call = await _send_files(
            client, chat_id, kind, media, caption=caption, reply_markup=reply_markup
        )
        if call.outcome is _Outcome.FAILED and _is_photo_rejected(call.response):
            logger.warning(
                "Telegram rejected photos for chat %s, retrying as documents", chat_id
            )
            kind = "document"
            call = await _send_files(
                client, chat_id, kind, media, caption=caption, reply_markup=reply_markup
            )
        if call.outcome is not _Outcome.SENT:
            return _MediaResult(
                call.outcome, chat_unreachable=_is_chat_unreachable(call.response)
            )
        return _MediaResult(call.outcome, _extract_uploaded(call.response, kind, len(media)))
    except Exception:
        # Что бы ни сломалось на фото, текст до чата доехать должен.
        logger.exception("Telegram photo notification failed for chat %s", chat_id)
        return _MediaResult(_Outcome.FAILED)


async def _send_text_after_media(
    client: httpx.AsyncClient,
    chat_id: str,
    text: str,
    reply_markup: dict | None,
    outcome: _Outcome,
    *,
    in_caption: bool,
) -> bool:
    """Текст с кнопками после фото.

    :return: получил ли чат текст (подписью или отдельным сообщением).
    """

    if in_caption:
        if outcome is _Outcome.SENT:
            return True
        if outcome is _Outcome.UNKNOWN:
            # Подпись могла дойти вместе с фото — текст стал бы дублем.
            return False
    # У альбома и у фото с длинным текстом сообщение с кнопками отдельное:
    # оно уходит при любом исходе фото и заодно служит фолбэком.
    return await _send_one(client, chat_id, text, reply_markup)


async def _deliver_uploaded(
    client: httpx.AsyncClient,
    chat_id: str,
    text: str,
    reply_markup: dict | None,
    uploaded: _Uploaded,
    *,
    in_caption: bool,
) -> bool:
    result = await _send_media(
        client,
        chat_id,
        uploaded,
        caption=text if in_caption else None,
        reply_markup=reply_markup if in_caption else None,
    )
    return await _send_text_after_media(
        client, chat_id, text, reply_markup, result.outcome, in_caption=in_caption
    )


async def _resolve_chat_ids(city_id: "UUID | None" = None) -> list[str]:
    """Определяет получателей для текущей рассылки.

    Сначала пытаемся взять активных (включённых и привязанных)
    подписчиков из БД. Если в БД ни одного активного — fallback на
    CSV из настроек, чтобы старый деплой без миграции продолжал
    работать.

    ``city_id`` — город события: к подписчикам сети добавятся подписчики
    этого города (франшизы). Без него уведомление идёт только сети.
    """

    try:
        # Импорт внутри функции, чтобы избежать кругового импорта на
        # этапе загрузки модуля (telegram_admin_subscribers тоже шлёт
        # запросы и в будущем может тянуть этот модуль).
        from backend.utils.telegram_admin_subscribers import get_active_chat_ids

        async with SessionLocal() as db:
            ids = await get_active_chat_ids(db, city_id=city_id)
        if ids:
            return ids
    except Exception:
        logger.exception("Failed to read telegram subscribers from DB")

    return [str(item) for item in settings.TELEGRAM_ADMIN_CHAT_IDS if item]


async def _notify_with_photos(
    client: httpx.AsyncClient,
    targets: Sequence[str],
    text: str,
    reply_markup: dict | None,
    photos: Sequence[PhotoFile],
) -> int:
    in_caption = len(photos) == 1 and telegram_text_length(text) <= TELEGRAM_CAPTION_LIMIT
    caption = text if in_caption else None
    photo_markup = reply_markup if in_caption else None

    delivered = 0
    remaining = [str(chat) for chat in targets]
    failed: list[str] = []
    uploaded: _Uploaded | None = None
    upload_failures = 0

    # Байты грузим по чатам по очереди, пока какой-нибудь чат их не примет:
    # заблокировавший бота подписчик в начале списка не должен лишать фото
    # всех остальных. Чату, у которого фото не ушло, текст пока не шлём —
    # как только появится file_id, он получит фото ещё раз. Сбои не по вине
    # чата (таймаут, 429, 5xx, фото не принято) скорее всего повторятся и в
    # следующем чате, поэтому после _UPLOAD_FAILURE_LIMIT таких сбоев
    # перестаём грузить байты и шлём текст.
    while remaining and uploaded is None and upload_failures < _UPLOAD_FAILURE_LIMIT:
        chat = remaining.pop(0)
        result = await _send_media(
            client, chat, photos, caption=caption, reply_markup=photo_markup
        )
        if result.outcome is not _Outcome.SENT and not result.chat_unreachable:
            upload_failures += 1
        if result.outcome is _Outcome.FAILED:
            failed.append(chat)
            continue
        uploaded = result.uploaded
        sent = await _send_text_after_media(
            client, chat, text, reply_markup, result.outcome, in_caption=in_caption
        )
        delivered += int(sent)

    if uploaded is not None:
        # Остальным чатам — те же файлы по file_id, без повторной загрузки.
        jobs = [
            _deliver_uploaded(
                client, chat, text, reply_markup, uploaded, in_caption=in_caption
            )
            for chat in (*failed, *remaining)
        ]
    else:
        if remaining:
            logger.warning(
                "Telegram photo upload failed %s times, sending text only to %s "
                "more chats without trying photos",
                upload_failures,
                len(remaining),
            )
        if failed:
            logger.warning(
                "Telegram photo upload failed for %s chats, sending text only",
                len(failed),
            )
        # Чаты с таймаутом после отправки сюда не попадают: у них текст
        # (или подпись) мог уже дойти, повтор был бы дублем.
        jobs = [
            _send_one(client, chat, text, reply_markup) for chat in (*failed, *remaining)
        ]

    results = await asyncio.gather(*jobs, return_exceptions=True)
    return delivered + sum(1 for result in results if result is True)


async def notify_admins(
    text: str,
    *,
    buttons: Iterable[InlineButton] = (),
    chat_ids: Sequence[str] | None = None,
    city_id: "UUID | None" = None,
    photos: Sequence[PhotoFile] = (),
) -> int:
    """Шлёт ``text`` всем активным подписчикам.

    :param buttons: список ``(label, url)`` для inline-клавиатуры.
        Каждая кнопка занимает свой ряд.
    :param chat_ids: переопределение получателей. Если ``None``,
        берутся из БД (или CSV-fallback из настроек).
    :param city_id: город события. Уведомление получат подписчики сети и
        подписчики этого города; без него — только подписчики сети.
    :param photos: фото ``(имя, байты, MIME)`` к уведомлению. Без них
        уходит обычное текстовое сообщение.
    :return: сколько чатов реально приняли сообщение. ``0`` означает, что
        уведомление никуда не ушло (нет токена, нет подписчиков или
        Telegram ответил ошибкой) — вызывающий код может это залогировать.
        Чаты, где запрос с фото упал по таймауту, не считаются: дошло ли
        сообщение, неизвестно.
    """

    if not settings.TELEGRAM_ADMIN_BOT_TOKEN:
        logger.debug("Telegram admin notifications skipped: no bot token")
        return 0

    if chat_ids is not None:
        targets = list(chat_ids)
    else:
        targets = await _resolve_chat_ids(city_id)

    if not targets:
        logger.debug("Telegram admin notifications skipped: no recipients")
        return 0

    reply_markup = _build_reply_markup(tuple(buttons))
    prepared_photos = list(photos)[:_MEDIA_GROUP_LIMIT]
    timeout = max(1.0, settings.TELEGRAM_API_TIMEOUT_SECONDS)

    if prepared_photos:
        async with httpx.AsyncClient(
            timeout=max(timeout, _PHOTO_TIMEOUT_SECONDS)
        ) as client:
            return await _notify_with_photos(
                client, targets, text, reply_markup, prepared_photos
            )

    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await asyncio.gather(
            *(_send_one(client, str(chat), text, reply_markup) for chat in targets),
            return_exceptions=True,
        )

    return sum(1 for result in results if result is True)


def fire_and_forget_notify(
    text: str,
    *,
    buttons: Iterable[InlineButton] = (),
    city_id: "UUID | None" = None,
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

    loop.create_task(notify_admins(text, buttons=tuple(buttons), city_id=city_id))


__all__ = [
    "InlineButton",
    "PhotoFile",
    "TELEGRAM_CAPTION_LIMIT",
    "escape_html",
    "fire_and_forget_notify",
    "notify_admins",
    "telegram_text_length",
]
