from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("payments.id"), index=True, nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
