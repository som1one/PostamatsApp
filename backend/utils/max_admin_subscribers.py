"""Сервисный слой для админских подписчиков MAX (max.ru).

Зеркало :mod:`backend.utils.telegram_admin_subscribers` — те же бизнес-правила:

- Username хранится без `@` и в нижнем регистре.
- Идентификаторы диалога (``chat_id`` / ``user_id``) заполняются
  автоматически, когда пользователь запускает бота: MAX присылает
  ``bot_started`` (или ``message_created`` с ``/start``) на webhook, а
  кнопка «Обновить связи» дополнительно вычитывает ``GET /updates``.
- Уведомление приходит, только если ``is_enabled is True`` и известен
  хотя бы один идентификатор диалога.

Отдельная таблица, а не колонки в telegram-подписчиках: ники в MAX и в
Telegram — разные пространства имён, и включать/выключать каналы админ
должен независимо.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.max_admin_subscriber import MaxAdminSubscriber
from backend.utils.max_bot import MaxRecipient, notify_admins as _send_via_max

logger = logging.getLogger(__name__)

# Ник в MAX: латиница, цифры и `_`, 5-32 символа, не начинается с цифры —
# те же правила, что мы применяем к Telegram.
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

# Секрет подписки MAX ограничен латиницей, цифрами и дефисом (5-256).
_WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9-]{5,256}$")

# Апдейты, ради которых мы держим подписку: оба означают «пользователь
# пришёл к боту», из обоих достаём идентификаторы диалога.
WEBHOOK_UPDATE_TYPES = ("bot_started", "message_created")

# Дефолтные подписчики, создаются один раз при старте приложения.
DEFAULT_SUBSCRIBERS: tuple[str, ...] = ("som1ones",)


class SubscriberError(Exception):
    """Бизнес-ошибка работы с подписчиками MAX."""

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


def recipient_of(sub: MaxAdminSubscriber) -> MaxRecipient | None:
    """Как адресовать сообщение подписчику: чат приоритетнее пользователя."""

    if sub.chat_id is not None:
        return ("chat_id", int(sub.chat_id))
    if sub.user_id is not None:
        return ("user_id", int(sub.user_id))
    return None


def serialize_subscriber(
    sub: MaxAdminSubscriber,
    city_name: str | None = None,
) -> dict:
    return {
        "id": str(sub.id),
        "username": sub.username,
        "chatId": sub.chat_id,
        "userId": sub.user_id,
        "isLinked": recipient_of(sub) is not None,
        "isEnabled": sub.is_enabled,
        "cityId": str(sub.city_id) if sub.city_id else None,
        "cityName": city_name,
        "note": sub.note,
        "createdAt": sub.created_at.isoformat() if sub.created_at else None,
        "updatedAt": sub.updated_at.isoformat() if sub.updated_at else None,
    }


async def list_subscribers(
    db: AsyncSession,
    *,
    city_id: UUID | None = None,
) -> list[MaxAdminSubscriber]:
    """Список подписчиков. ``city_id`` — только подписчики этого города."""

    stmt = select(MaxAdminSubscriber).order_by(MaxAdminSubscriber.created_at.asc())
    if city_id is not None:
        stmt = stmt.where(MaxAdminSubscriber.city_id == city_id)
    return list((await db.scalars(stmt)).all())


async def create_subscriber(
    db: AsyncSession,
    *,
    username: str,
    note: str | None = None,
    is_enabled: bool = True,
    city_id: UUID | None = None,
) -> MaxAdminSubscriber:
    normalized = normalize_username(username)
    existing = (
        await db.execute(
            select(MaxAdminSubscriber).where(
                MaxAdminSubscriber.username == normalized
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise SubscriberError("SUBSCRIBER_ALREADY_EXISTS", 409)

    subscriber = MaxAdminSubscriber(
        username=normalized,
        note=(note or None),
        is_enabled=is_enabled,
        city_id=city_id,
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
    require_city_id: UUID | None = None,
) -> MaxAdminSubscriber:
    subscriber = await db.get(MaxAdminSubscriber, subscriber_id)
    if subscriber is None:
        raise SubscriberError("SUBSCRIBER_NOT_FOUND", 404)
    if require_city_id is not None and subscriber.city_id != require_city_id:
        # Для франшизы чужой подписчик просто «не существует».
        raise SubscriberError("SUBSCRIBER_NOT_FOUND", 404)
    if is_enabled is not None:
        subscriber.is_enabled = is_enabled
    if note is not None:
        # Пустую строку трактуем как очистку поля.
        subscriber.note = note.strip() or None
    await db.commit()
    await db.refresh(subscriber)
    return subscriber


async def delete_subscriber(
    db: AsyncSession,
    subscriber_id: UUID,
    *,
    require_city_id: UUID | None = None,
) -> None:
    subscriber = await db.get(MaxAdminSubscriber, subscriber_id)
    if subscriber is None:
        raise SubscriberError("SUBSCRIBER_NOT_FOUND", 404)
    if require_city_id is not None and subscriber.city_id != require_city_id:
        raise SubscriberError("SUBSCRIBER_NOT_FOUND", 404)
    await db.delete(subscriber)
    await db.commit()


async def get_active_recipients(
    db: AsyncSession,
    *,
    city_id: UUID | None = None,
) -> list[MaxRecipient]:
    """Адресаты рассылки: включённые и уже связанные подписчики.

    ``city_id`` — город события: получатели это подписчики сети
    (``city_id IS NULL``) плюс подписчики этого города. Без города
    (общесетевое событие) — только подписчики сети, чтобы франчайзи не
    получали чужие уведомления.
    """

    stmt = select(MaxAdminSubscriber).where(
        MaxAdminSubscriber.is_enabled.is_(True),
        or_(
            MaxAdminSubscriber.chat_id.is_not(None),
            MaxAdminSubscriber.user_id.is_not(None),
        ),
    )
    if city_id is None:
        stmt = stmt.where(MaxAdminSubscriber.city_id.is_(None))
    else:
        stmt = stmt.where(
            or_(
                MaxAdminSubscriber.city_id.is_(None),
                MaxAdminSubscriber.city_id == city_id,
            )
        )
    rows = (await db.scalars(stmt)).all()
    recipients = [recipient_of(row) for row in rows]
    return [item for item in recipients if item is not None]


async def ensure_default_subscribers(db: AsyncSession) -> None:
    """Создаёт дефолтных подписчиков, если их ещё нет (идемпотентно)."""

    if not DEFAULT_SUBSCRIBERS:
        return

    existing_usernames = {
        row.username
        for row in (
            await db.scalars(
                select(MaxAdminSubscriber).where(
                    MaxAdminSubscriber.username.in_(DEFAULT_SUBSCRIBERS)
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
            MaxAdminSubscriber(
                username=normalized,
                is_enabled=True,
                note="Создан автоматически",
            )
        )
        created += 1
    if created:
        await db.commit()
        logger.info("Created %d default MAX admin subscribers", created)


# ---------------------------------------------------------------------------
# Разбор апдейтов MAX
# ---------------------------------------------------------------------------


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _username_of(user: dict) -> str | None:
    # В разных версиях API ник приезжает то как `username`, то как
    # `nickname`; берём первое непустое.
    for key in ("username", "nickname"):
        value = user.get(key)
        if value:
            return str(value).lstrip("@").lower()
    return None


class _ParsedUpdate:
    """Плоское представление апдейта MAX: только то, что нам нужно."""

    __slots__ = ("update_type", "username", "chat_id", "user_id", "text")

    def __init__(
        self,
        *,
        update_type: str,
        username: str | None,
        chat_id: int | None,
        user_id: int | None,
        text: str,
    ) -> None:
        self.update_type = update_type
        self.username = username
        self.chat_id = chat_id
        self.user_id = user_id
        self.text = text

    @property
    def recipient(self) -> MaxRecipient | None:
        if self.chat_id is not None:
            return ("chat_id", self.chat_id)
        if self.user_id is not None:
            return ("user_id", self.user_id)
        return None

    @property
    def is_start(self) -> bool:
        if self.update_type == "bot_started":
            return True
        return self.text == "/start" or self.text.startswith("/start ")


def parse_update(update: dict) -> _ParsedUpdate:
    """Достаёт из апдейта ник, идентификаторы диалога и текст.

    Терпимо относится к форме payload-а: у ``bot_started`` пользователь
    лежит в ``user`` и ``chat_id`` в корне, у ``message_created`` — в
    ``message.sender`` и ``message.recipient.chat_id``. ``user_id``
    берём только из отправителя: ``recipient.user_id`` в диалоге может
    указывать на самого бота.
    """

    if not isinstance(update, dict):
        return _ParsedUpdate(
            update_type="", username=None, chat_id=None, user_id=None, text=""
        )

    message = _as_dict(update.get("message"))
    sender = _as_dict(message.get("sender"))
    recipient = _as_dict(message.get("recipient"))
    body = _as_dict(message.get("body"))
    user = _as_dict(update.get("user"))

    return _ParsedUpdate(
        update_type=str(update.get("update_type") or ""),
        username=_username_of(user) or _username_of(sender),
        chat_id=_int_or_none(update.get("chat_id"))
        or _int_or_none(recipient.get("chat_id")),
        user_id=_int_or_none(user.get("user_id"))
        or _int_or_none(sender.get("user_id")),
        text=str(body.get("text") or update.get("text") or "").strip(),
    )


# ---------------------------------------------------------------------------
# Resync через GET /updates
# ---------------------------------------------------------------------------


def _require_token() -> str:
    token = settings.MAX_ADMIN_BOT_TOKEN
    if not token:
        raise SubscriberError("MAX_BOT_TOKEN_NOT_CONFIGURED", 503)
    return token


def _api_url(path: str) -> str:
    base = (settings.MAX_API_BASE_URL or "").rstrip("/")
    if not base:
        raise SubscriberError("MAX_API_BASE_URL_NOT_CONFIGURED", 503)
    return f"{base}/{path.lstrip('/')}"


async def _max_request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    timeout: float | None = None,
) -> dict:
    token = _require_token()
    url = _api_url(path)
    request_timeout = timeout or max(1.0, settings.MAX_API_TIMEOUT_SECONDS)
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            response = await client.request(
                method, url, params=params, json=json, headers=headers
            )
    except httpx.RequestError as exc:
        logger.warning("MAX %s %s network error: %s", method, path, exc)
        raise SubscriberError("MAX_API_NETWORK_ERROR", 502) from exc

    if response.status_code >= 400:
        logger.warning(
            "MAX %s %s non-2xx: %s %s",
            method,
            path,
            response.status_code,
            response.text[:200],
        )
        raise SubscriberError("MAX_API_ERROR", 502)

    try:
        payload = response.json()
    except ValueError as exc:
        raise SubscriberError("MAX_API_ERROR", 502) from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        return {"result": payload}
    return payload


async def _fetch_updates_identities() -> dict[str, tuple[int | None, int | None]]:
    """``username_lower -> (chat_id, user_id)`` из последних апдейтов бота.

    ``timeout=0`` отключает long polling: кнопке «Обновить связи» нужен
    мгновенный ответ, а не 30-секундное ожидание новых событий.
    """

    payload = await _max_request(
        "GET", "updates", params={"limit": 100, "timeout": 0}
    )
    updates = payload.get("updates")
    if not isinstance(updates, list):
        updates = []

    identities: dict[str, tuple[int | None, int | None]] = {}
    for raw in updates:
        parsed = parse_update(raw if isinstance(raw, dict) else {})
        if not parsed.username:
            continue
        if parsed.chat_id is None and parsed.user_id is None:
            continue
        previous = identities.get(parsed.username, (None, None))
        identities[parsed.username] = (
            parsed.chat_id if parsed.chat_id is not None else previous[0],
            parsed.user_id if parsed.user_id is not None else previous[1],
        )
    return identities


async def resync_chat_ids(db: AsyncSession) -> dict:
    """Сматчить username-ы с идентификаторами диалогов из ``GET /updates``.

    Не перезаписывает уже связанных подписчиков. Возвращает отчёт
    ``{linked, alreadyLinked, missing, updatesSeen}``.
    """

    identities = await _fetch_updates_identities()

    subscribers = await list_subscribers(db)
    linked = 0
    already_linked = 0
    missing: list[str] = []

    for sub in subscribers:
        if recipient_of(sub) is not None:
            already_linked += 1
            continue
        identity = identities.get(sub.username)
        if identity is None:
            missing.append(sub.username)
            continue
        chat_id, user_id = identity
        sub.chat_id = chat_id
        sub.user_id = user_id
        linked += 1

    if linked:
        await db.commit()

    return {
        "linked": linked,
        "alreadyLinked": already_linked,
        "missing": missing,
        "updatesSeen": len(identities),
    }


# ---------------------------------------------------------------------------
# Входящий webhook (обрабатывает запуск бота)
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

NO_USERNAME_MESSAGE = (
    "Чтобы получать уведомления, поставь себе @username в MAX "
    "и попроси администратора добавить его в список подписчиков."
)


async def _send_message(recipient: MaxRecipient, text: str) -> None:
    """Служебный ответ пользователю. Ошибки уже проглочены транспортом."""

    if not settings.MAX_ADMIN_BOT_TOKEN:
        return
    await _send_via_max(text, recipients=[recipient])


async def handle_max_update(db: AsyncSession, update: dict) -> dict:
    """Обрабатывает входящий апдейт MAX.

    Интересует только запуск бота: если username уже добавлен админом —
    связываем идентификаторы диалога и отвечаем приветствием. Если нет —
    отвечаем «попроси добавить тебя», запись не создаём, чтобы случайные
    люди не плодили подписчиков.
    """

    parsed = parse_update(update)
    recipient = parsed.recipient
    if recipient is None:
        return {"handled": False, "reason": "no_chat"}

    if not parsed.is_start:
        return {"handled": False, "reason": "not_start"}

    if not parsed.username:
        # Без ника админ не сможет добавить — отвечаем понятным текстом.
        await _send_message(recipient, NO_USERNAME_MESSAGE)
        return {"handled": True, "reason": "no_username"}

    subscriber = (
        await db.execute(
            select(MaxAdminSubscriber).where(
                MaxAdminSubscriber.username == parsed.username
            )
        )
    ).scalar_one_or_none()

    if subscriber is None:
        await _send_message(recipient, NOT_ALLOWED_MESSAGE)
        return {"handled": True, "reason": "not_in_allowlist"}

    changed = False
    if parsed.chat_id is not None and subscriber.chat_id != parsed.chat_id:
        subscriber.chat_id = parsed.chat_id
        changed = True
    if parsed.user_id is not None and subscriber.user_id != parsed.user_id:
        subscriber.user_id = parsed.user_id
        changed = True
    if changed:
        await db.commit()

    await _send_message(recipient, WELCOME_MESSAGE)
    return {"handled": True, "reason": "linked"}


# ---------------------------------------------------------------------------
# Управление подпиской на webhook (MAX: /subscriptions)
# ---------------------------------------------------------------------------


def _require_webhook_secret() -> str:
    secret = settings.MAX_WEBHOOK_SECRET
    if not secret:
        raise SubscriberError("MAX_WEBHOOK_SECRET_NOT_CONFIGURED", 503)
    if not _WEBHOOK_SECRET_RE.fullmatch(secret):
        # MAX принимает в секрете только латиницу, цифры и дефис —
        # проверяем на нашей стороне, чтобы не ловить невнятный 400.
        raise SubscriberError("MAX_WEBHOOK_SECRET_INVALID", 400)
    return secret


def _webhook_url(public_origin: str | None) -> str:
    secret = _require_webhook_secret()

    # Приоритет: явный ADMIN_PANEL_URL (чистый домен без портов) →
    # затем origin текущего запроса (фолбэк, если переменная не задана).
    base = ""
    admin = (settings.ADMIN_PANEL_URL or "").rstrip("/")
    if admin:
        base = admin[: -len("/admin")] if admin.endswith("/admin") else admin
    if not base:
        base = (public_origin or "").rstrip("/")
    if not base:
        raise SubscriberError("MAX_WEBHOOK_BASE_URL_REQUIRED", 503)
    return f"{base}/max/webhook/{secret}"


async def set_max_webhook(public_origin: str | None = None) -> dict:
    url = _webhook_url(public_origin)
    payload = {
        "url": url,
        "update_types": list(WEBHOOK_UPDATE_TYPES),
        "secret": _require_webhook_secret(),
    }
    data = await _max_request("POST", "subscriptions", json=payload)
    return {"url": url, "result": data}


async def delete_max_webhook(public_origin: str | None = None) -> dict:
    url = _webhook_url(public_origin)
    data = await _max_request("DELETE", "subscriptions", params={"url": url})
    return {"url": url, "result": data}


async def get_max_webhook_info() -> dict:
    data = await _max_request("GET", "subscriptions")
    return {"info": data.get("subscriptions", data)}
