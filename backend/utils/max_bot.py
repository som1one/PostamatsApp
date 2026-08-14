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

Если ``MAX_ADMIN_BOT_TOKEN`` не задан, функция тихо ничего не делает:
dev и тесты работают с тем же конфигом, что и прод.
"""

from __future__ import annotations

import asyncio
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

# Получатель: ("chat_id" | "user_id", идентификатор). MAX адресует
# сообщение одним из двух параметров, и какой именно доступен — зависит
# от апдейта, по которому мы подписчика связали.
MaxRecipient = tuple[str, int]

_TAG_RE = re.compile(r"<[^>]+>")

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


def _auth_headers() -> dict[str, str]:
    token = settings.MAX_ADMIN_BOT_TOKEN
    if not token:
        raise RuntimeError("MAX_ADMIN_BOT_TOKEN is not configured")
    return {"Authorization": token, "Content-Type": "application/json"}


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
    except httpx.RequestError:
        logger.exception("MAX sendMessage failed for %s=%s", key, value)
        return None


async def _send_one(
    client: httpx.AsyncClient,
    recipient: MaxRecipient,
    text: str,
    attachments: list[dict] | None,
) -> bool:
    body: dict[str, object] = {"text": text, "format": "html"}
    if attachments is not None:
        body["attachments"] = attachments

    response = await _post_message(client, recipient, body)
    if response is None:
        return False

    if response.status_code < 400:
        return True

    key, value = recipient
    # 400 обычно значит «не понравилась разметка», 403/404 — бот не запущен
    # или чат недоступен. На разметку отвечаем повтором в плоском виде,
    # остальное просто логируем: клиентский запрос из-за MAX падать не должен.
    if response.status_code == 400:
        logger.warning(
            "MAX rejected html message for %s=%s, retrying as plain text: %s",
            key,
            value,
            response.text[:200],
        )
        plain: dict[str, object] = {"text": to_plain_text(text)}
        if attachments is not None:
            plain["attachments"] = attachments
        retry = await _post_message(client, recipient, plain)
        if retry is not None and retry.status_code < 400:
            return True
        if retry is not None:
            logger.warning(
                "MAX plain-text retry failed for %s=%s: %s %s",
                key,
                value,
                retry.status_code,
                retry.text[:200],
            )
        return False

    logger.warning(
        "MAX sendMessage non-2xx for %s=%s: %s %s",
        key,
        value,
        response.status_code,
        response.text[:200],
    )
    return False


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
) -> int:
    """Шлёт ``text`` всем активным подписчикам MAX.

    :param buttons: список ``(label, url)``; каждая кнопка занимает свой ряд.
    :param recipients: переопределение получателей. Если ``None``, берутся
        из БД (или CSV-fallback из настроек).
    :param city_id: город события. Уведомление получат подписчики сети и
        подписчики этого города; без него — только подписчики сети.
    :return: сколько адресатов реально приняли сообщение.
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
    timeout = max(1.0, settings.MAX_API_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await asyncio.gather(
            *(_send_one(client, target, text, attachments) for target in targets),
            return_exceptions=True,
        )

    return sum(1 for result in results if result is True)


__all__ = [
    "InlineButton",
    "MaxRecipient",
    "notify_admins",
    "parse_recipient",
    "to_plain_text",
]
