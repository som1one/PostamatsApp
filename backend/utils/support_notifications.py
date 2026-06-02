"""Telegram admin notifications for support-chat lifecycle events.

Mirrors the verification-request notification pattern from ``routers/me.py``:
builds an HTML-safe message text plus an optional ``Открыть в админке`` inline
button, then hands it to :func:`backend.utils.telegram_bot.fire_and_forget_notify`
so it is delivered to the same Telegram admin subscribers that already receive
verification notifications.

Two events are notified:

* **First contact** — a brand-new ``SupportConversation`` row was just inserted
  (the client opened support for the first time). Emitted by
  :func:`notify_support_conversation_created`.
* **New client message** — the client sent a message. Emitted by
  :func:`notify_support_client_message`. To avoid spam, callers should restrict
  this to interesting transitions (e.g. ``conversation_was_reopened``);
  routine follow-ups in an already-open conversation are not notified.

All public functions are fire-and-forget; they never raise and never block the
caller. The message body, if included, is truncated and HTML-escaped.
"""

from __future__ import annotations

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


def _build_support_admin_link(conversation_id: UUID) -> str | None:
    base = settings.ADMIN_PANEL_URL
    if not base:
        return None
    return f"{base.rstrip('/')}/?section=support&conversation={conversation_id}"


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
    link = _build_support_admin_link(conversation_id)
    if link:
        buttons.append(("Открыть в админке", link))
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


def notify_support_client_message(
    user: User,
    conversation: SupportConversation,
    message: SupportMessage,
    *,
    conversation_was_created: bool,
    conversation_was_reopened: bool,
) -> None:
    """Fire a Telegram notification for an interesting client message.

    Notifies on first contact (a freshly inserted conversation) or on a client
    message that reopens a previously closed conversation. Routine messages
    inside an already-open conversation are intentionally NOT notified to keep
    the admin channel quiet during active chats.

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
