"""Минимальная интеграция с MAX Bot API (max.ru) для админских уведомлений.

Зеркало :mod:`backend.utils.telegram_bot`: тот же контракт
(``notify_admins(text, buttons=...)`` c HTML-текстом), но другой транспорт.
Обе реализации дёргает диспетчер
:mod:`backend.utils.admin_notifications`, поэтому одно и то же уведомление
уходит и в Telegram, и в MAX.

Отличия MAX от Telegram, которые пришлось учесть:

- Токен передаётся заголовком ``Authorization``, query-параметр
  ``access_token`` в актуальной версии API больше не поддерживается.
- Адресат — query-параметр ``chat_id`` **или** ``user_id``; в теле его нет.
- Клавиатуры нет как отдельного поля: inline-кнопки лежат в
  ``attachments`` элементом ``{"type": "inline_keyboard", ...}``.
- Разметка включается полем ``format: "html"``. Если MAX не сварит нашу
  разметку, шлём тот же текст плоским — уведомление важнее оформления.
- Фото сначала загружаются: ``POST /uploads?type=image`` выдаёт адрес
  загрузки, туда уходит multipart с полем ``data``, в ответ — ``token``.
  Токен кладётся в ``attachments`` элементом ``{"type": "image", ...}`` и
  годится для всех адресатов, поэтому байты грузим один раз. Сразу после
  загрузки MAX может ответить ``attachment.not.ready`` — это не ошибка
  разметки, а «подождите»: повторяем с паузами. Картинку, которую MAX не
  принял (например, слишком большие стороны), грузим ещё раз как файл
  (``type=file``). После двух фото, которые так и не загрузились,
  остальные не грузим: сбой, скорее всего, не в фото, а текст ждёт
  загрузок. Если фото так и не ушло, адресат получает обычный текст.
- Таймаут, когда запрос с фото уже ушёл, — не повод слать текст: сообщение
  могло дойти, и оператор получил бы дубль.

Если ``MAX_ADMIN_BOT_TOKEN`` не задан, функция тихо ничего не делает:
dev и тесты работают с тем же конфигом, что и прод.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import re
from html import unescape
from typing import Iterable, Sequence
from uuid import UUID

import httpx

from backend.core.database import SessionLocal
from backend.core.settings import settings

logger = logging.getLogger(__name__)

# Кнопка-ссылка: (подпись, url) — тот же тип, что у telegram_bot.
InlineButton = tuple[str, str]

# Фото для отправки: (имя файла, байты, MIME) — тот же тип, что у telegram_bot.
PhotoFile = tuple[str, bytes, str]

# Получатель: ("chat_id" | "user_id", идентификатор). MAX адресует
# сообщение одним из двух параметров, и какой именно доступен — зависит
# от апдейта, по которому мы подписчика связали.
MaxRecipient = tuple[str, int]

_TAG_RE = re.compile(r"<[^>]+>")

# Загрузка фото заметно дольше обычной отправки текста.
_PHOTO_TIMEOUT_SECONDS = 30.0

# Паузы между повторами, пока MAX обрабатывает загруженное фото.
_ATTACHMENT_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0, 2.0)

_ATTACHMENT_NOT_READY = "attachment.not.ready"

# Таймауты, после которых сообщение могло дойти до MAX: тело уже ушло
# (или уходило), просто ответа не дождались. Повторять такое нельзя.
_MAYBE_DELIVERED_ERRORS = (httpx.ReadTimeout, httpx.WriteTimeout)

# Сколько фото может не загрузиться (ни картинкой, ни файлом, или по
# таймауту), прежде чем остальные мы грузить перестанем: каждая попытка —
# до 30 с, а текст операторам ждёт, пока загрузки закончатся.
_UPLOAD_FAILURE_LIMIT = 2

_RECIPIENT_KEYS = {
    "chat": "chat_id",
    "chat_id": "chat_id",
    "user": "user_id",
    "user_id": "user_id",
}


def _api_url(path: str) -> str:
    base = (settings.MAX_API_BASE_URL or "").rstrip("/")
    if not base:
        raise RuntimeError("MAX_API_BASE_URL is not configured")
    return f"{base}/{path.lstrip('/')}"


def _token_headers() -> dict[str, str]:
    token = settings.MAX_ADMIN_BOT_TOKEN
    if not token:
        raise RuntimeError("MAX_ADMIN_BOT_TOKEN is not configured")
    return {"Authorization": token}


def _auth_headers() -> dict[str, str]:
    return {**_token_headers(), "Content-Type": "application/json"}


def parse_recipient(raw: str | MaxRecipient | None) -> MaxRecipient | None:
    """Разбирает получателя из строки конфига или пары.

    Поддерживаются ``"12345"`` (чат), ``"chat:12345"`` и ``"user:12345"``.
    Мусорные значения дают ``None`` — CSV из .env не должен ронять рассылку.
    """

    if raw is None:
        return None
    if isinstance(raw, tuple):
        kind, value = raw
        key = _RECIPIENT_KEYS.get(str(kind).strip().lower())
        if key is None:
            return None
        try:
            return (key, int(value))
        except (TypeError, ValueError):
            return None

    text = str(raw).strip()
    if not text:
        return None
    kind = "chat_id"
    if ":" in text:
        prefix, _, rest = text.partition(":")
        mapped = _RECIPIENT_KEYS.get(prefix.strip().lower())
        if mapped is None:
            return None
        kind, text = mapped, rest.strip()
    try:
        return (kind, int(text))
    except ValueError:
        return None


def to_plain_text(text: str) -> str:
    """HTML-сообщение → плоский текст (fallback, если MAX не принял разметку)."""

    return unescape(_TAG_RE.sub("", text))


def _build_attachments(buttons: Sequence[InlineButton]) -> list[dict] | None:
    rows = [
        [{"type": "link", "text": label, "url": url}]
        for label, url in buttons
        if label and url
    ]
    if not rows:
        return None
    return [{"type": "inline_keyboard", "payload": {"buttons": rows}}]


async def _post_message(
    client: httpx.AsyncClient,
    recipient: MaxRecipient,
    body: dict,
) -> httpx.Response | None:
    key, value = recipient
    try:
        return await client.post(
            _api_url("messages"),
            params={key: value},
            headers=_auth_headers(),
            json=body,
        )
    except _MAYBE_DELIVERED_ERRORS:
        # Не «не ушло», а «неизвестно»: решает вызывающий код.
        raise
    except httpx.RequestError:
        logger.exception("MAX sendMessage failed for %s=%s", key, value)
        return None


def _is_attachment_not_ready(response: httpx.Response) -> bool:
    if response.status_code < 400:
        return False
    return _ATTACHMENT_NOT_READY in (response.text or "")


async def _post_message_when_ready(
    client: httpx.AsyncClient,
    recipient: MaxRecipient,
    body: dict,
) -> httpx.Response | None:
    """POST /messages с повторами, пока MAX не дообработал вложения."""

    response = await _post_message(client, recipient, body)
    for delay in _ATTACHMENT_RETRY_DELAYS:
        if response is None or not _is_attachment_not_ready(response):
            break
        await asyncio.sleep(delay)
        response = await _post_message(client, recipient, body)
    return response


class _Delivery(enum.Enum):
    SENT = "sent"
    # MAX ответил ошибкой или запрос не ушёл — можно слать фолбэк.
    FAILED = "failed"
    # Таймаут после отправки: сообщение могло дойти, повторять нельзя.
    UNKNOWN = "unknown"


async def _deliver(
    client: httpx.AsyncClient,
    recipient: MaxRecipient,
    text: str,
    attachments: list[dict] | None,
) -> _Delivery:
    body: dict[str, object] = {"text": text, "format": "html"}
    if attachments is not None:
        body["attachments"] = attachments

    key, value = recipient
    try:
        response = await _post_message_when_ready(client, recipient, body)
        if response is None:
            return _Delivery.FAILED

        if response.status_code < 400:
            return _Delivery.SENT

        # 400 обычно значит «не понравилась разметка», 403/404 — бот не запущен
        # или чат недоступен. На разметку отвечаем повтором в плоском виде,
        # остальное просто логируем: клиентский запрос из-за MAX падать не должен.
        # ``attachment.not.ready`` тоже приходит ошибкой, но разметка тут ни при
        # чём — повторы уже исчерпаны, плоский текст не поможет.
        if response.status_code == 400 and not _is_attachment_not_ready(response):
            logger.warning(
                "MAX rejected html message for %s=%s, retrying as plain text: %s",
                key,
                value,
                response.text[:200],
            )
            plain: dict[str, object] = {"text": to_plain_text(text)}
            if attachments is not None:
                plain["attachments"] = attachments
            retry = await _post_message_when_ready(client, recipient, plain)
            if retry is not None and retry.status_code < 400:
                return _Delivery.SENT
            if retry is not None:
                logger.warning(
                    "MAX plain-text retry failed for %s=%s: %s %s",
                    key,
                    value,
                    retry.status_code,
                    retry.text[:200],
                )
            return _Delivery.FAILED
    except _MAYBE_DELIVERED_ERRORS:
        logger.warning(
            "MAX sendMessage timed out for %s=%s after the request was sent, "
            "not resending",
            key,
            value,
        )
        return _Delivery.UNKNOWN

    logger.warning(
        "MAX sendMessage non-2xx for %s=%s: %s %s",
        key,
        value,
        response.status_code,
        response.text[:200],
    )
    return _Delivery.FAILED


async def _send_one(
    client: httpx.AsyncClient,
    recipient: MaxRecipient,
    text: str,
    attachments: list[dict] | None,
) -> bool:
    return await _deliver(client, recipient, text, attachments) is _Delivery.SENT


def _extract_upload_token(payload: object) -> str | None:
    """Токен из ответа сервера загрузки.

    Актуальный API отвечает ``{"token": ...}``, старые версии —
    ``{"photos": {<id>: {"token": ...}}}``; понимаем обе формы.
    """

    if not isinstance(payload, dict):
        return None
    token = payload.get("token")
    if isinstance(token, str) and token:
        return token
    photos = payload.get("photos")
    if isinstance(photos, dict):
        for item in photos.values():
            if isinstance(item, dict):
                token = item.get("token")
                if isinstance(token, str) and token:
                    return token
    return None


async def _upload(
    client: httpx.AsyncClient, photo: PhotoFile, upload_type: str
) -> str | None:
    """Загружает одно фото как ``upload_type`` (image/file) и возвращает токен.

    Таймауты пробрасываются наружу: медленную загрузку нет смысла повторять
    другим типом, а текст операторам ждёт, пока загрузки закончатся.
    """

    filename, content, mime_type = photo
    try:
        slot = await client.post(
            _api_url("uploads"),
            params={"type": upload_type},
            headers=_token_headers(),
        )
        if slot.status_code >= 400:
            logger.warning(
                "MAX %s upload slot non-2xx for %s: %s %s",
                upload_type,
                filename,
                slot.status_code,
                slot.text[:200],
            )
            return None
        slot_payload = slot.json()
        upload_url = slot_payload.get("url") if isinstance(slot_payload, dict) else None
        if not isinstance(upload_url, str) or not upload_url:
            logger.warning("MAX %s upload slot without url for %s", upload_type, filename)
            return None

        # Адрес загрузки — отдельный сервер MAX: токен бота ему не нужен
        # (в документации его там нет), а Content-Type с boundary httpx
        # выставит сам — JSON-заголовок из _auth_headers тут сломал бы тело.
        uploaded = await client.post(
            upload_url,
            files={"data": (filename, content, mime_type)},
        )
        if uploaded.status_code >= 400:
            logger.warning(
                "MAX %s upload non-2xx for %s: %s %s",
                upload_type,
                filename,
                uploaded.status_code,
                uploaded.text[:200],
            )
            return None
        try:
            uploaded_payload = uploaded.json()
        except ValueError:
            uploaded_payload = None
        # Для части типов MAX отдаёт токен сразу со слотом, а не после загрузки.
        token = _extract_upload_token(uploaded_payload) or _extract_upload_token(
            slot_payload
        )
    except httpx.TimeoutException:
        raise
    except Exception:
        logger.exception("MAX %s upload failed for %s", upload_type, filename)
        return None

    if token is None:
        logger.warning("MAX %s upload returned no token for %s", upload_type, filename)
    return token


async def _upload_attachment(
    client: httpx.AsyncClient, photo: PhotoFile
) -> dict | None:
    """Вложение для одного фото: картинкой, а если не вышло — файлом.

    Картинку MAX может не принять (стороны больше допустимых, не смог
    обработать), у файла таких проверок нет — оператор хотя бы откроет фото.
    """

    filename = photo[0]
    try:
        token = await _upload(client, photo, "image")
        if token:
            return {"type": "image", "payload": {"token": token}}
        logger.warning("MAX image upload failed for %s, retrying as file", filename)
        token = await _upload(client, photo, "file")
        if token:
            return {"type": "file", "payload": {"token": token}}
    except httpx.TimeoutException:
        logger.warning("MAX upload timed out for %s, skipping photo", filename)
    return None


async def _upload_attachments(
    client: httpx.AsyncClient, photos: Sequence[PhotoFile]
) -> list[dict]:
    """Загружает фото по очереди; не загрузившиеся просто пропускаются.

    После ``_UPLOAD_FAILURE_LIMIT`` незагрузившихся фото остальные не грузим.
    """

    attachments: list[dict] = []
    failures = 0
    for index, photo in enumerate(photos):
        if failures >= _UPLOAD_FAILURE_LIMIT:
            logger.warning(
                "MAX photo upload failed %s times, skipping %s more photos",
                failures,
                len(photos) - index,
            )
            break
        attachment = await _upload_attachment(client, photo)
        if attachment is None:
            failures += 1
            continue
        attachments.append(attachment)
    return attachments


async def _send_with_media(
    client: httpx.AsyncClient,
    recipient: MaxRecipient,
    text: str,
    media: list[dict],
    keyboard: list[dict] | None,
) -> bool:
    delivery = await _deliver(client, recipient, text, [*media, *(keyboard or [])])
    if delivery is _Delivery.SENT:
        return True
    if delivery is _Delivery.UNKNOWN:
        # Сообщение с фото могло дойти — текст без фото стал бы дублем.
        return False
    key, value = recipient
    logger.warning(
        "MAX message with photos failed for %s=%s, sending text only", key, value
    )
    return await _send_one(client, recipient, text, keyboard)


async def _resolve_recipients(city_id: "UUID | None" = None) -> list[MaxRecipient]:
    """Получатели рассылки: активные подписчики из БД, иначе CSV из настроек.

    ``city_id`` — город события: к подписчикам сети добавятся подписчики
    этого города (франшизы).
    """

    try:
        # Импорт внутри функции — max_admin_subscribers тянет этот модуль
        # ради отправки служебных ответов, и на уровне модуля это был бы
        # круговой импорт.
        from backend.utils.max_admin_subscribers import get_active_recipients

        async with SessionLocal() as db:
            recipients = await get_active_recipients(db, city_id=city_id)
        if recipients:
            return recipients
    except Exception:
        logger.exception("Failed to read MAX subscribers from DB")

    parsed = [parse_recipient(item) for item in settings.MAX_ADMIN_CHAT_IDS]
    return [item for item in parsed if item is not None]


async def notify_admins(
    text: str,
    *,
    buttons: Iterable[InlineButton] = (),
    recipients: Sequence[MaxRecipient] | None = None,
    city_id: "UUID | None" = None,
    photos: Sequence[PhotoFile] = (),
) -> int:
    """Шлёт ``text`` всем активным подписчикам MAX.

    :param buttons: список ``(label, url)``; каждая кнопка занимает свой ряд.
    :param recipients: переопределение получателей. Если ``None``, берутся
        из БД (или CSV-fallback из настроек).
    :param city_id: город события. Уведомление получат подписчики сети и
        подписчики этого города; без него — только подписчики сети.
    :param photos: фото ``(имя, байты, MIME)``; загружаются один раз и
        уходят вложениями перед клавиатурой. Не загрузилось ни одно —
        уходит обычный текст.
    :return: сколько адресатов реально приняли сообщение. Адресаты, где
        отправка с фото упала по таймауту, не считаются: дошло ли, неизвестно.
    """

    if not settings.MAX_ADMIN_BOT_TOKEN:
        logger.debug("MAX admin notifications skipped: no bot token")
        return 0

    targets = (
        list(recipients)
        if recipients is not None
        else await _resolve_recipients(city_id)
    )
    if not targets:
        logger.debug("MAX admin notifications skipped: no recipients")
        return 0

    attachments = _build_attachments(tuple(buttons))
    prepared_photos = list(photos)
    timeout = max(1.0, settings.MAX_API_TIMEOUT_SECONDS)
    if prepared_photos:
        timeout = max(timeout, _PHOTO_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout) as client:
        media = (
            await _upload_attachments(client, prepared_photos) if prepared_photos else []
        )
        if prepared_photos and not media:
            logger.warning("MAX photo upload failed, sending text only")
        if media:
            # Токены загрузки общие для всех адресатов — байты ушли один раз.
            jobs = [
                _send_with_media(client, target, text, media, attachments)
                for target in targets
            ]
        else:
            jobs = [_send_one(client, target, text, attachments) for target in targets]
        results = await asyncio.gather(*jobs, return_exceptions=True)

    return sum(1 for result in results if result is True)


__all__ = [
    "InlineButton",
    "MaxRecipient",
    "PhotoFile",
    "notify_admins",
    "parse_recipient",
    "to_plain_text",
]
