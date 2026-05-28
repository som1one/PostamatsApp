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
