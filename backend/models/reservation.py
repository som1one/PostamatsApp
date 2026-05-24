from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import ReservationStatus


class Reservation(Base, TimestampMixin):
    __tablename__ = "reservations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("products.id"), index=True, nullable=False)
    inventory_unit_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("inventory_units.id"),
        index=True,
        nullable=False,
    )
    locker_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("locker_locations.id"),
        index=True,
        nullable=False,
    )
    price_plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("price_plans.id"), index=True, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        SQLAlchemyEnum(ReservationStatus, name="reservation_status"),
        default=ReservationStatus.CREATED,
        index=True,
        nullable=False,
    )
    duration_type: Mapped[str] = mapped_column(String, nullable=False)
    duration_value: Mapped[int] = mapped_column(nullable=False)
    quoted_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    preauth_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Время, на которое пользователь оформил выдачу. Может быть в будущем
    # (например, "завтра"). Используется для блокировки `open-cell` до
    # этого момента и для расчёта `planned_end_at`. NULL — значит "сразу".
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
