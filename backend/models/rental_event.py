from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum as SQLAlchemyEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import RentalEventSource, RentalStatus


class RentalEvent(Base, TimestampMixin):
    __tablename__ = "rental_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    rental_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("rentals.id"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    from_status: Mapped[RentalStatus | None] = mapped_column(
        SQLAlchemyEnum(RentalStatus, name="rental_status"),
        nullable=True,
    )
    to_status: Mapped[RentalStatus | None] = mapped_column(
        SQLAlchemyEnum(RentalStatus, name="rental_status"),
        nullable=True,
    )
    source: Mapped[RentalEventSource] = mapped_column(
        SQLAlchemyEnum(RentalEventSource, name="rental_event_source"),
        index=True,
        nullable=False,
    )
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    