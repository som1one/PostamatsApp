"""Подписчик Telegram-бота на админские уведомления.

Админ заранее заводит запись по @username, пользователь шлёт боту
``/start``. Дальше команда «обновить связи» вызывает Telegram
``getUpdates``, и для каждого username-а с ``chat_id is null``
сохраняется найденный chat_id. С этого момента уведомления приходят
только тем подписчикам, у которых ``is_enabled = True`` и есть
``chat_id``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class TelegramAdminSubscriber(Base):
    __tablename__ = "telegram_admin_subscribers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # Telegram username хранится без `@` и в нижнем регистре, чтобы
    # сопоставление с ``chat.username`` из getUpdates было устойчивым.
    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    # Заполняется автоматически после первого `/start` пользователя.
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
