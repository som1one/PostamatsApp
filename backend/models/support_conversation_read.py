from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class SupportConversationRead(Base):
    __tablename__ = "support_conversation_reads"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("support_conversations.id"),
        index=True,
        nullable=False,
    )
    operator_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("admin_accounts.id"),
        index=True,
        nullable=False,
    )
    # Наибольший message `seq`, который этот оператор уже видел.
    last_read_seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "operator_id",
            name="uq_support_conversation_reads_conversation_operator",
        ),
    )
