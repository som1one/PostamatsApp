"""Отправка служебных писем через SMTP (сейчас — копии обращений на почту).

Стандартный ``smtplib`` блокирующий, поэтому отправка уходит в поток через
``asyncio.to_thread``. Как и уведомления в мессенджеры, это fire-and-forget:
ошибка SMTP логируется и не ломает запрос пользователя — обращение к этому
моменту уже сохранено в базе и видно в админке.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Sequence

from backend.core.settings import settings

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def email_configured() -> bool:
    return bool(settings.SMTP_USER and settings.SMTP_PASSWORD)


def build_message(
    *,
    subject: str,
    body: str,
    to: Sequence[str],
    reply_to: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    # Яндекс отклоняет письмо, если From не совпадает с логином SMTP.
    message["From"] = formataddr(("Напрокатберу", settings.SMTP_USER or ""))
    message["To"] = ", ".join(to)
    if reply_to:
        # «Ответить» в почте сразу пишет автору обращения.
        message["Reply-To"] = reply_to
    message["Message-ID"] = make_msgid(domain="naprokatberu.ru")
    message.set_content(body)
    return message


def _send_sync(message: EmailMessage) -> None:
    context = ssl.create_default_context()
    timeout = settings.SMTP_TIMEOUT_SECONDS
    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout, context=context
        ) as client:
            client.login(settings.SMTP_USER or "", settings.SMTP_PASSWORD or "")
            client.send_message(message)
        return
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout) as client:
        client.starttls(context=context)
        client.login(settings.SMTP_USER or "", settings.SMTP_PASSWORD or "")
        client.send_message(message)


async def send_email(message: EmailMessage) -> bool:
    if not email_configured():
        logger.debug("SMTP is not configured, skipping email %r", message["Subject"])
        return False
    try:
        await asyncio.to_thread(_send_sync, message)
    except Exception:  # noqa: BLE001 — письмо не должно ронять запрос
        logger.exception("Failed to send email %r", message["Subject"])
        return False
    return True


def fire_and_forget_email(message: EmailMessage) -> None:
    if not email_configured():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running event loop, skipping email")
        return
    task = loop.create_task(send_email(message))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


__all__ = [
    "build_message",
    "email_configured",
    "fire_and_forget_email",
    "send_email",
]
