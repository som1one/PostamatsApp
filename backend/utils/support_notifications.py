"""Telegram admin notifications for support-chat lifecycle events.

Mirrors the verification-request notification pattern from ``routers/me.py``:
builds an HTML-safe message text plus an optional ``Открыть в админке`` inline
button, then hands it to :func:`backend.utils.telegram_bot.fire_and_forget_notify`
so it is delivered to the same Telegram admin subscribers that already receive
verification notifications.

Three events are notified:

* **First contact** — a brand-new ``SupportConversation`` row was just inserted
  (the client opened support for the first time). Emitted by
  :func:`notify_support_conversation_created`.
* **Reopen** — a client message reopened a previously closed conversation.
* **New client message** — the client wrote in an already-open conversation.
  To keep the admin channel quiet during bursts, a follow-up within
  ``_ROUTINE_NOTIFY_COOLDOWN`` of the client's previous message is NOT
  notified: the first message of a burst pings, the rest stay silent.

All public functions are fire-and-forget; they never raise and never block the
caller. The message body, if included, is truncated and HTML-escaped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from backend.core.settings import settings
from backend.models.support_conversation import SupportConversation
from backend.models.support_message import SupportMessage
from backend.models.user import User
from backend.utils.telegram_bot import escape_html, fire_and_forget_notify

# Hard cap on how much of the client message body we include in the Telegram
# notification. Telegram caps a single message at ~4096 chars; we want plenty
# of headroom for the header, button labels, and HTML escaping overhead.
_MESSAGE_PREVIEW_LIMIT = 500

# Гашение «пачек»: если предыдущее клиентское сообщение было меньше этого
# времени назад, повторный телеграм-пинг не шлём — первый пинг пачки админ
# уже получил, а во время живого диалога оператор и так в панели.
_ROUTINE_NOTIFY_COOLDOWN = timedelta(minutes=10)


def _as_utc(value: datetime) -> datetime:
    # SQLite отдаёт naive datetime, Postgres — aware; нормализуем для вычитания.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _build_support_panel_link(conversation_id: UUID) -> str | None:
    """Диалоги поддержки живут в хелпер-панели на сайте, не в админке.

    Секции «support» в админке нет — ссылка туда открывала пустую страницу.
    """
    base = settings.WEB_APP_ORIGIN
    if not base:
        return None
    return f"{base.rstrip('/')}/helperpanel?conversation={conversation_id}"


def _display_name(user: User) -> str:
    full_name = " ".join(
        part for part in (user.last_name, user.first_name) if part
    ).strip()
    return full_name or "Без имени"


def _truncate(text: str, limit: int = _MESSAGE_PREVIEW_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _build_buttons(conversation_id: UUID) -> list[tuple[str, str]]:
    buttons: list[tuple[str, str]] = []
    link = _build_support_panel_link(conversation_id)
    if link:
        buttons.append(("Открыть диалог", link))
    return buttons


def _build_new_conversation_text(user: User, message_body: str | None) -> str:
    lines = [
        "🆘 <b>Новое обращение в поддержку</b>",
        f"👤 {escape_html(_display_name(user))}",
    ]
    if user.phone:
        lines.append(f"📞 {escape_html(user.phone)}")
    if message_body:
        preview = _truncate(message_body.strip())
        if preview:
            lines.append("")
            lines.append(f"💬 {escape_html(preview)}")
    return "\n".join(lines)


def _build_reopened_text(user: User, message_body: str | None) -> str:
    lines = [
        "🔁 <b>Возобновлено обращение в поддержку</b>",
        f"👤 {escape_html(_display_name(user))}",
    ]
    if user.phone:
        lines.append(f"📞 {escape_html(user.phone)}")
    if message_body:
        preview = _truncate(message_body.strip())
        if preview:
            lines.append("")
            lines.append(f"💬 {escape_html(preview)}")
    return "\n".join(lines)


def notify_support_conversation_created(
    user: User,
    conversation: SupportConversation,
    *,
    first_message: SupportMessage | None = None,
) -> None:
    """Fire a Telegram notification for a brand-new support conversation.

    Safe to call from a request handler after ``await db.commit()``; never
    raises. Pass ``first_message`` when available to include a short preview
    of the body in the notification.
    """
    body = first_message.body if first_message is not None else None
    text = _build_new_conversation_text(user, body)
    fire_and_forget_notify(text, buttons=_build_buttons(conversation.id))


def _build_new_message_text(user: User, message_body: str | None) -> str:
    lines = [
        "💬 <b>Новое сообщение в поддержку</b>",
        f"👤 {escape_html(_display_name(user))}",
    ]
    if user.phone:
        lines.append(f"📞 {escape_html(user.phone)}")
    if message_body:
        preview = _truncate(message_body.strip())
        if preview:
            lines.append("")
            lines.append(f"💬 {escape_html(preview)}")
    return "\n".join(lines)


def notify_support_client_message(
    user: User,
    conversation: SupportConversation,
    message: SupportMessage,
    *,
    conversation_was_created: bool,
    conversation_was_reopened: bool,
    previous_client_message_at: datetime | None = None,
) -> None:
    """Fire a Telegram notification for a client support message.

    Notifies on first contact, on reopening a closed conversation, and on a
    regular message in an open conversation — the latter with burst
    suppression: if the client's PREVIOUS message was sent less than
    ``_ROUTINE_NOTIFY_COOLDOWN`` ago, the ping is skipped (the first message
    of the burst already notified the admins). Callers pass
    ``previous_client_message_at`` from
    :class:`~backend.services.support_chat_service.PostedClientMessage`;
    when it is ``None`` the cooldown anchors on ``conversation.created_at``
    instead — the widget creates the conversation on open (which already
    pings «Новое обращение»), so the first message moments later must not
    ping twice.

    Safe to call after ``await db.commit()``; never raises.
    """
    if conversation_was_created:
        notify_support_conversation_created(
            user, conversation, first_message=message
        )
        return
    if conversation_was_reopened:
        text = _build_reopened_text(user, message.body)
        fire_and_forget_notify(text, buttons=_build_buttons(conversation.id))
        return

    # Якорь кулдауна: прошлое клиентское сообщение, а если его нет — момент
    # создания диалога. Виджет создаёт диалог при открытии (и это уже шлёт
    # «Новое обращение»), поэтому первое сообщение секунды спустя не должно
    # пинговать второй раз.
    anchor = previous_client_message_at or conversation.created_at
    if anchor is not None and message.created_at is not None:
        elapsed = _as_utc(message.created_at) - _as_utc(anchor)
        if elapsed < _ROUTINE_NOTIFY_COOLDOWN:
            return

    text = _build_new_message_text(user, message.body)
    fire_and_forget_notify(text, buttons=_build_buttons(conversation.id))
