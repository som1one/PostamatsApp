from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import ReturnRequestStatus


class ReturnRequest(Base, TimestampMixin):
    __tablename__ = "return_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    rental_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("rentals.id"),
        index=True,
        nullable=False,
    )
    locker_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("locker_locations.id"),
        index=True,
        nullable=False,
    )
    cell_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("locker_cells.id"),
        index=True,
        nullable=False,
    )
    pin: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ReturnRequestStatus] = mapped_column(
        SQLAlchemyEnum(ReturnRequestStatus, name="return_request_status"),
        default=ReturnRequestStatus.CREATED,
        index=True,
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
