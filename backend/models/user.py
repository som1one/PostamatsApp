from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, Enum as SQLAlchemyEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import VerificationStatus


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    phone: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    middle_name: Mapped[str | None] = mapped_column(String, nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    preferred_city_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("cities.id"),
        index=True,
        nullable=True,
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SQLAlchemyEnum(VerificationStatus, name="verification_status"),
        default=VerificationStatus.DRAFT,
        index=True,
        nullable=False,
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blocked_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
