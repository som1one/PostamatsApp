"""Подписчик MAX-бота на админские уведомления.

Зеркало :class:`~backend.models.telegram_admin_subscriber.TelegramAdminSubscriber`:
админ заранее заводит запись по @username, пользователь запускает бота в
MAX (кнопка «Начать» или ``/start``). Апдейт ``bot_started`` /
``message_created`` приходит на webhook, и мы сохраняем идентификаторы
диалога. Уведомления идут только тем, у кого ``is_enabled = True`` и есть
``chat_id`` либо ``user_id``.

Почему два идентификатора: MAX адресует сообщение query-параметром
``chat_id`` или ``user_id``, и какой из них известен — зависит от
апдейта. ``bot_started`` даёт оба, ``message_created`` — chat_id
получателя и user_id отправителя. Храним что дали, шлём по chat_id, а
если его нет — по user_id.

``city_id`` работает как у Telegram-подписчиков: ``NULL`` — подписчик
сети (получает всё), заполненный город — подписчик франшизы (только
события своего города).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class MaxAdminSubscriber(Base):
    __tablename__ = "max_admin_subscribers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # Username в MAX хранится без `@` и в нижнем регистре — сопоставление
    # с апдейтом должно быть устойчивым к регистру.
    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    # Заполняются автоматически после первого запуска бота пользователем.
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # NULL — уведомления по всей сети; город — только события этого города.
    city_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("cities.id"),
        index=True,
        nullable=True,
    )
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
