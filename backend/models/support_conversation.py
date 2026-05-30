from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import ConversationStatus


class SupportConversation(Base, TimestampMixin):
    __tablename__ = "support_conversations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # Один разговор на клиента: unique по user_id делает get-or-create
    # безопасным upsert-ом (Requirement 1.2/1.3).
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
        unique=True,
        index=True,
        nullable=False,
    )
    status: Mapped[ConversationStatus] = mapped_column(
        SQLAlchemyEnum(
            ConversationStatus,
            name="conversation_status",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        default=ConversationStatus.OPEN,
        nullable=False,
    )
    assigned_operator_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("admin_accounts.id"),
        nullable=True,
    )
    # Ключ сортировки для операторского списка (Requirement 9.2).
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=True,
    )
    # Денормализованный ordering key последнего сообщения (tiebreak сортировки).
    last_message_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
