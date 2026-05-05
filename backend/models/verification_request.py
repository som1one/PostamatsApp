from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Date, DateTime, Enum as SQLAlchemyEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import DocumentType, VerificationStatus


class VerificationRequest(Base, TimestampMixin):
    __tablename__ = "verification_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    status: Mapped[VerificationStatus] = mapped_column(
        SQLAlchemyEnum(VerificationStatus, name="verification_status"),
        default=VerificationStatus.DRAFT,
        index=True,
        nullable=False,
    )
    document_type: Mapped[DocumentType] = mapped_column(
        SQLAlchemyEnum(DocumentType, name="document_type"),
        index=True,
        nullable=False,
    )
    document_name: Mapped[str | None] = mapped_column(String, nullable=True)
    document_number: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    document_issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    front_file_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("media_files.id"),
        index=True,
        nullable=True,
    )
    back_file_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("media_files.id"),
        index=True,
        nullable=True,
    )
    selfie_file_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("media_files.id"),
        index=True,
        nullable=True,
    )
    reviewed_by_admin_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("admin_users.id"),
        index=True,
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_check_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    provider_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
