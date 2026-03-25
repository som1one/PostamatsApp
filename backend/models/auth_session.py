from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import AuthPlatform


class AuthSession(Base, TimestampMixin):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    platform: Mapped[AuthPlatform] = mapped_column(
        SQLAlchemyEnum(AuthPlatform, name="auth_platform"),
        default=AuthPlatform.WEB,
        index=True,
        nullable=False,
    )
    device_name: Mapped[str | None] = mapped_column(String, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String, nullable=True)
