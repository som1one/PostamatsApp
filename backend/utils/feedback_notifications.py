"""Подписи и админские уведомления для раздела «Обратная связь».

Одно место, где обращение превращается в текст: и админка, и уведомления
берут человекочитаемые подписи темы и источника отсюда, чтобы «Мобильное
приложение» в карточке и в телеге называлось одинаково.

Уведомление уходит через :mod:`backend.utils.admin_notifications` — то есть
сразу в Telegram и в MAX, тем же подписчикам, что получают верификации и
поддержку. Текст HTML-безопасен: все пользовательские поля экранируются.
"""

from __future__ import annotations

from uuid import UUID

from backend.core.settings import settings
from backend.models.enums import FeedbackSource, FeedbackTopic
from backend.models.feedback_message import FeedbackMessage
from backend.utils.admin_notifications import escape_html, fire_and_forget_notify

# Столько текста обращения кладём в уведомление. Telegram режет сообщение
# на ~4096 символах, оставляем запас на заголовок и экранирование.
_MESSAGE_PREVIEW_LIMIT = 700

_TOPIC_LABELS: dict[str, str] = {
    FeedbackTopic.IDEA.value: "Идея для аренды",
    FeedbackTopic.FRANCHISE.value: "Заявка на франшизу",
    FeedbackTopic.OTHER.value: "Обращение",
}

_TOPIC_EMOJI: dict[str, str] = {
    FeedbackTopic.IDEA.value: "💡",
    FeedbackTopic.FRANCHISE.value: "🤝",
    FeedbackTopic.OTHER.value: "📨",
}

_SOURCE_LABELS: dict[str, str] = {
    FeedbackSource.WEB.value: "Сайт",
    FeedbackSource.MOBILE.value: "Мобильное приложение",
    FeedbackSource.UNKNOWN.value: "Источник не определён",
}


def topic_label(topic: str | None) -> str:
    return _TOPIC_LABELS.get(topic or "", _TOPIC_LABELS[FeedbackTopic.OTHER.value])


def source_label(source: str | None) -> str:
    return _SOURCE_LABELS.get(
        source or "", _SOURCE_LABELS[FeedbackSource.UNKNOWN.value]
    )


def _truncate(text: str, limit: int = _MESSAGE_PREVIEW_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_admin_link(feedback_id: UUID | None = None) -> str | None:
    base = settings.ADMIN_PANEL_URL
    if not base:
        return None
    link = f"{base.rstrip('/')}/?section=feedback"
    if feedback_id is not None:
        link += f"&item={feedback_id}"
    return link


def build_feedback_notification(
    record: FeedbackMessage,
) -> tuple[str, list[tuple[str, str]]]:
    """HTML-текст уведомления и inline-кнопки для одного обращения.

    Если админский deep-link недоступен (не задан ADMIN_PANEL_URL), кнопок
    не будет — текст всё равно уйдёт.
    """

    emoji = _TOPIC_EMOJI.get(record.topic or "", _TOPIC_EMOJI[FeedbackTopic.OTHER.value])
    lines = [
        f"{emoji} <b>{escape_html(topic_label(record.topic))}</b>",
        f"📍 Откуда: {escape_html(source_label(record.source))}",
        f"👤 {escape_html(record.name)}",
    ]
    if record.phone:
        lines.append(f"📞 {escape_html(record.phone)}")
    if record.email:
        lines.append(f"✉️ {escape_html(record.email)}")
    if record.city:
        lines.append(f"🏙 {escape_html(record.city)}")
    if record.reference_url:
        lines.append(f"🔗 {escape_html(record.reference_url)}")
    if record.photo_id is not None:
        lines.append("📷 Приложено фото")
    message = (record.message or "").strip()
    if message:
        lines.append("")
        lines.append(f"💬 {escape_html(_truncate(message))}")

    buttons: list[tuple[str, str]] = []
    link = build_admin_link(record.id)
    if link:
        buttons.append(("Открыть в админке", link))

    return "\n".join(lines), buttons


def notify_feedback_created(record: FeedbackMessage) -> None:
    """Шлёт уведомление о новом обращении в Telegram и MAX.

    Fire-and-forget: безопасно звать сразу после ``await db.commit()``,
    исключений не бросает и запрос не задерживает.
    """

    text, buttons = build_feedback_notification(record)
    fire_and_forget_notify(text, buttons=buttons)


__all__ = [
    "build_admin_link",
    "build_feedback_notification",
    "notify_feedback_created",
    "source_label",
    "topic_label",
]
