from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import RentalStatus


class Rental(Base, TimestampMixin):
    __tablename__ = "rentals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    reservation_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("reservations.id"),
        unique=True,
        nullable=True,
    )
    inventory_unit_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("inventory_units.id"),
        index=True,
        nullable=False,
    )
    pickup_locker_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("locker_locations.id"),
        index=True,
        nullable=False,
    )
    return_locker_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("locker_locations.id"),
        index=True,
        nullable=True,
    )
    pickup_pin: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[RentalStatus] = mapped_column(
        SQLAlchemyEnum(RentalStatus, name="rental_status"),
        default=RentalStatus.PICKUP_READY,
        index=True,
        nullable=False,
    )
    pickup_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
