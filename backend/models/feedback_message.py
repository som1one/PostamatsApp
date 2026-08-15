from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from backend.models.enums import FeedbackSource, FeedbackTopic


class FeedbackMessage(Base):
    """Обращение из любой публичной формы: раздел «Обратная связь» в админке.

    Сюда стекается всё, что посетитель написал нам сам — идея для аренды с
    сайта или из приложения, заявка на франшизу. Формы публичные, гость
    может не быть авторизован, поэтому FK на пользователя нет.

    ``topic`` — что за обращение, ``source`` — из какого клиента оно
    прилетело; оба хранятся строкой, а не SQL-enum, чтобы новая форма
    добавлялась без миграции типа. Значения берём из
    :class:`~backend.models.enums.FeedbackTopic` и
    :class:`~backend.models.enums.FeedbackSource`.

    Контакт обязателен «хотя бы один»: у идеи это email, у заявки на
    франшизу — телефон. Фото опционально и привязывается к существующей
    таблице media_files (через kind=RENTAL_IDEA_PHOTO).
    """

    __tablename__ = "feedback_messages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    topic: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=FeedbackTopic.OTHER.value,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=FeedbackSource.UNKNOWN.value,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reference_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    photo_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("media_files.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
