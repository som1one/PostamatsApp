from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import AuthVerificationSessionStatus


class AuthVerificationSession(Base, TimestampMixin):
    __tablename__ = "auth_verification_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    phone: Mapped[str] = mapped_column(String, index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[AuthVerificationSessionStatus] = mapped_column(
        SQLAlchemyEnum(
            AuthVerificationSessionStatus,
            name="auth_verification_session_status",
        ),
        default=AuthVerificationSessionStatus.PENDING,
        index=True,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    request_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    request_user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirm_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    confirm_user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
