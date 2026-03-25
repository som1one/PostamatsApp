from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import PaymentStatus, PaymentType


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    reservation_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("reservations.id"),
        index=True,
        nullable=True,
    )
    rental_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("rentals.id"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    type: Mapped[PaymentType] = mapped_column(
        SQLAlchemyEnum(PaymentType, name="payment_type"),
        index=True,
        nullable=False,
    )
    status: Mapped[PaymentStatus] = mapped_column(
        SQLAlchemyEnum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.CREATED,
        index=True,
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String, default="RUB", nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
