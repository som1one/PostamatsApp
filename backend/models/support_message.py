from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from backend.models.enums import MessageAuthorType


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("support_conversations.id"),
        index=True,
        nullable=False,
    )
    # Глобально монотонный ordering key из Postgres sequence
    # `support_message_seq`. Значение присваивается в сервисном слое /
    # миграции; сама колонка — просто not-null bigint.
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author_type: Mapped[MessageAuthorType] = mapped_column(
        SQLAlchemyEnum(
            MessageAuthorType,
            name="message_author_type",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    author_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
        nullable=True,
    )
    author_admin_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("admin_accounts.id"),
        nullable=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_support_messages_conversation_seq", "conversation_id", "seq"),
    )
