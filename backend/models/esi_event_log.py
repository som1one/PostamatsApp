from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin


class EsiEventLog(Base, TimestampMixin):
    __tablename__ = "esi_event_log"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider_event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    locker_external_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    cell_external_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_result: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    matched_rental_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("rentals.id"),
        index=True,
        nullable=True,
    )
    matched_return_request_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("return_requests.id"),
        index=True,
        nullable=True,
    )
