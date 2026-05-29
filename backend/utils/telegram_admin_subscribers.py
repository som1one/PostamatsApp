"""Сервисный слой для админских Telegram-подписчиков.

Бизнес-правила:

- Username хранится без `@` и в нижнем регистре (Telegram username
  case-insensitive).
- `chat_id` заполняется автоматически из ``getUpdates`` после того, как
  пользователь нажал у бота ``/start``. До этого подписчик есть в
  списке, но уведомления ему не идут.
- Уведомление приходит, только если ``is_enabled is True`` и
  ``chat_id is not None``.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.telegram_admin_subscriber import TelegramAdminSubscriber

logger = logging.getLogger(__name__)

# Telegram username: 5-32 chars, латиница, цифры и `_`. Не должен начинаться с цифры.
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

# Дефолтные подписчики, создаются один раз при старте приложения.
DEFAULT_SUBSCRIBERS: tuple[str, ...] = ("som1ones",)


class SubscriberError(Exception):
    """Бизнес-ошибка работы с подписчиками."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def normalize_username(raw: str | None) -> str:
    if not raw:
        raise SubscriberError("USERNAME_REQUIRED", 400)
    cleaned = raw.strip().lstrip("@")
    if not _USERNAME_RE.fullmatch(cleaned):
        raise SubscriberError("USERNAME_INVALID", 400)
    return cleaned.lower()


def serialize_subscriber(sub: TelegramAdminSubscriber) -> dict:
    return {
        "id": str(sub.id),
        "username": sub.username,
        "chatId": sub.chat_id,
        "isLinked": sub.chat_id is not None,
        "isEnabled": sub.is_enabled,
        "note": sub.note,
        "createdAt": sub.created_at.isoformat() if sub.created_at else None,
        "updatedAt": sub.updated_at.isoformat() if sub.updated_at else None,
    }


async def list_subscribers(db: AsyncSession) -> list[TelegramAdminSubscriber]:
    stmt = select(TelegramAdminSubscriber).order_by(
        TelegramAdminSubscriber.created_at.asc()
    )
    return list((await db.scalars(stmt)).all())


async def create_subscriber(
    db: AsyncSession,
    *,
    username: str,
    note: str | None = None,
    is_enabled: bool = True,
) -> TelegramAdminSubscriber:
    normalized = normalize_username(username)
    existing = (
        await db.execute(
            select(TelegramAdminSubscriber).where(
                TelegramAdminSubscriber.username == normalized
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise SubscriberError("SUBSCRIBER_ALREADY_EXISTS", 409)

    subscriber = TelegramAdminSubscriber(
        username=normalized,
        note=(note or None),
        is_enabled=is_enabled,
    )
    db.add(subscriber)
    await db.commit()
    await db.refresh(subscriber)
    return subscriber


async def update_subscriber(
    db: AsyncSession,
    subscriber_id: UUID,
    *,
    is_enabled: bool | None = None,
    note: str | None = None,
) -> TelegramAdminSubscriber:
    subscriber = await db.get(TelegramAdminSubscriber, subscriber_id)
    if subscriber is None:
        raise SubscriberError("SUBSCRIBER_NOT_FOUND", 404)
    if is_enabled is not None:
        subscriber.is_enabled = is_enabled
    if note is not None:
        # Пустую строку трактуем как очистку поля.
        subscriber.note = note.strip() or None
    await db.commit()
    await db.refresh(subscriber)
    return subscriber


async def delete_subscriber(db: AsyncSession, subscriber_id: UUID) -> None:
    subscriber = await db.get(TelegramAdminSubscriber, subscriber_id)
    if subscriber is None:
        raise SubscriberError("SUBSCRIBER_NOT_FOUND", 404)
    await db.delete(subscriber)
    await db.commit()


async def get_active_chat_ids(db: AsyncSession) -> list[str]:
    """Адресаты для текущей рассылки уведомлений.

    Возвращает chat_id только тех подписчиков, которые включены и уже
    привязаны (нажали ``/start``).
    """

    stmt = select(TelegramAdminSubscriber).where(
        TelegramAdminSubscriber.is_enabled.is_(True),
        TelegramAdminSubscriber.chat_id.is_not(None),
    )
    rows = (await db.scalars(stmt)).all()
    return [str(row.chat_id) for row in rows]


async def ensure_default_subscribers(db: AsyncSession) -> None:
    """Создаёт дефолтных подписчиков, если их ещё нет.

    Идемпотентно: повторный запуск ничего не меняет, существующие
    записи не трогаются (даже если они отключены).
    """

    if not DEFAULT_SUBSCRIBERS:
        return

    existing_usernames = {
        row.username
        for row in (
            await db.scalars(
                select(TelegramAdminSubscriber).where(
                    TelegramAdminSubscriber.username.in_(DEFAULT_SUBSCRIBERS)
                )
            )
        ).all()
    }
    created = 0
    for username in DEFAULT_SUBSCRIBERS:
        normalized = username.lower()
        if normalized in existing_usernames:
            continue
        db.add(
            TelegramAdminSubscriber(
                username=normalized,
                is_enabled=True,
                note="Создан автоматически",
            )
        )
        created += 1
    if created:
        await db.commit()
        logger.info("Created %d default telegram admin subscribers", created)


# ---------------------------------------------------------------------------
# Resync via Telegram getUpdates
# ---------------------------------------------------------------------------


async def _fetch_updates_chats() -> dict[str, int]:
    """Возвращает map ``username_lower -> chat_id`` из последних апдейтов бота.

    Telegram возвращает до 100 апдейтов за вызов, и они могут уехать,
    если их не подтверждать. Для сценария «админ добавил username,
    пользователь нажал /start, админ кликнул Resync» этого достаточно.
    """

    token = settings.TELEGRAM_ADMIN_BOT_TOKEN
    if not token:
        raise SubscriberError("TELEGRAM_BOT_TOKEN_NOT_CONFIGURED", 503)

    timeout = max(1.0, settings.TELEGRAM_API_TIMEOUT_SECONDS)
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params={"allowed_updates": ["message"]})
    except httpx.RequestError as exc:
        logger.warning("Telegram getUpdates network error: %s", exc)
        raise SubscriberError("TELEGRAM_API_NETWORK_ERROR", 502) from exc

    if response.status_code >= 400:
        logger.warning(
            "Telegram getUpdates non-2xx: %s %s",
            response.status_code,
            response.text[:200],
        )
        raise SubscriberError("TELEGRAM_API_ERROR", 502)

    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise SubscriberError("TELEGRAM_API_ERROR", 502)

    chats: dict[str, int] = {}
    for update in payload.get("result", []) or []:
        msg = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
            or {}
        )
        chat = msg.get("chat") or {}
        username = chat.get("username")
        chat_id = chat.get("id")
        if not username or chat_id is None:
            continue
        chats[str(username).lower()] = int(chat_id)
    return chats


async def resync_chat_ids(db: AsyncSession) -> dict:
    """Сматчить username-ы с chat_id из ``getUpdates``.

    - Не перезаписывает уже привязанные chat_id (мы доверяем тому, что
      сохранили после первого матча).
    - Возвращает отчёт ``{linked: n, alreadyLinked: n, missing: [...]}``.
    """

    chats = await _fetch_updates_chats()

    subscribers = await list_subscribers(db)
    linked = 0
    already_linked = 0
    missing: list[str] = []

    for sub in subscribers:
        if sub.chat_id is not None:
            already_linked += 1
            continue
        chat_id = chats.get(sub.username)
        if chat_id is None:
            missing.append(sub.username)
            continue
        sub.chat_id = chat_id
        linked += 1

    if linked:
        await db.commit()

    return {
        "linked": linked,
        "alreadyLinked": already_linked,
        "missing": missing,
        "updatesSeen": len(chats),
    }


# ---------------------------------------------------------------------------
# Inbound webhook from Telegram (handles /start)
# ---------------------------------------------------------------------------


WELCOME_MESSAGE = (
    "👋 Готово, ты в подписке на админ-уведомления Naprokatberu.\n"
    "Сюда будут приходить новые заявки на верификацию и другие события.\n\n"
    "Управление подписчиками — в разделе «Уведомления» в админке."
)

NOT_ALLOWED_MESSAGE = (
    "Привет. Этот бот рассылает админ-уведомления Naprokatberu.\n"
    "Доступ выдаёт администратор по @username — попроси добавить тебя."
)


async def _send_message(chat_id: int, text: str) -> None:
    token = settings.TELEGRAM_ADMIN_BOT_TOKEN
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    timeout = max(1.0, settings.TELEGRAM_API_TIMEOUT_SECONDS)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
        if response.status_code >= 400:
            logger.warning(
                "Telegram sendMessage non-2xx for chat %s: %s %s",
                chat_id,
                response.status_code,
                response.text[:200],
            )
    except httpx.RequestError:
        logger.exception("Telegram sendMessage failed for chat %s", chat_id)


async def handle_telegram_update(db: AsyncSession, update: dict) -> dict:
    """Обрабатывает входящий апдейт от Telegram.

    Сейчас интересует только ``/start`` в личке: если username уже
    добавлен админом — связываем chat_id, отвечаем приветствием. Если
    нет — отвечаем «попроси добавить тебя», запись в БД не создаём,
    чтобы рандомные люди не плодили подписчиков.
    """

    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    username = (chat.get("username") or "").lower()

    if chat_id is None:
        return {"handled": False, "reason": "no_chat"}

    is_start = text == "/start" or text.startswith("/start ")
    if not is_start:
        return {"handled": False, "reason": "not_start"}

    if not username:
        # Без username админ не сможет добавить, отвечаем понятным текстом.
        await _send_message(
            int(chat_id),
            "Чтобы получать уведомления, поставь себе @username в Telegram "
            "и попроси администратора добавить его в список подписчиков.",
        )
        return {"handled": True, "reason": "no_username"}

    subscriber = (
        await db.execute(
            select(TelegramAdminSubscriber).where(
                TelegramAdminSubscriber.username == username
            )
        )
    ).scalar_one_or_none()

    if subscriber is None:
        await _send_message(int(chat_id), NOT_ALLOWED_MESSAGE)
        return {"handled": True, "reason": "not_in_allowlist"}

    changed = False
    if subscriber.chat_id != int(chat_id):
        subscriber.chat_id = int(chat_id)
        changed = True
    if changed:
        await db.commit()

    await _send_message(int(chat_id), WELCOME_MESSAGE)
    return {"handled": True, "reason": "linked"}


# ---------------------------------------------------------------------------
# Webhook lifecycle helpers
# ---------------------------------------------------------------------------


async def _telegram_post(method: str, payload: dict) -> dict:
    token = settings.TELEGRAM_ADMIN_BOT_TOKEN
    if not token:
        raise SubscriberError("TELEGRAM_BOT_TOKEN_NOT_CONFIGURED", 503)
    url = f"https://api.telegram.org/bot{token}/{method}"
    timeout = max(1.0, settings.TELEGRAM_API_TIMEOUT_SECONDS)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
    except httpx.RequestError as exc:
        logger.warning("Telegram %s network error: %s", method, exc)
        raise SubscriberError("TELEGRAM_API_NETWORK_ERROR", 502) from exc

    if response.status_code >= 400:
        logger.warning(
            "Telegram %s non-2xx: %s %s",
            method,
            response.status_code,
            response.text[:200],
        )
        raise SubscriberError("TELEGRAM_API_ERROR", 502)

    data = response.json()
    if not isinstance(data, dict) or not data.get("ok"):
        raise SubscriberError("TELEGRAM_API_ERROR", 502)
    return data


def _webhook_url(public_origin: str | None) -> str:
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    if not secret:
        raise SubscriberError("TELEGRAM_WEBHOOK_SECRET_NOT_CONFIGURED", 503)

    # Приоритет: явный ADMIN_PANEL_URL (чистый домен без портов) →
    # затем origin текущего запроса (фолбэк, если переменная не задана).
    base = ""
    admin = (settings.ADMIN_PANEL_URL or "").rstrip("/")
    if admin:
        base = admin[: -len("/admin")] if admin.endswith("/admin") else admin
    if not base:
        base = (public_origin or "").rstrip("/")
    if not base:
        raise SubscriberError("TELEGRAM_WEBHOOK_BASE_URL_REQUIRED", 503)
    return f"{base}/telegram/webhook/{secret}"


async def set_telegram_webhook(public_origin: str | None = None) -> dict:
    url = _webhook_url(public_origin)
    payload = {
        "url": url,
        "allowed_updates": ["message"],
        "drop_pending_updates": False,
        "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
    }
    data = await _telegram_post("setWebhook", payload)
    return {"url": url, "result": data.get("result")}


async def delete_telegram_webhook() -> dict:
    data = await _telegram_post("deleteWebhook", {"drop_pending_updates": False})
    return {"result": data.get("result")}


async def get_telegram_webhook_info() -> dict:
    data = await _telegram_post("getWebhookInfo", {})
    return {"info": data.get("result")}
