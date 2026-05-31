from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from backend.models.enums import MediaFileKind


class MediaFile(Base):
    __tablename__ = "media_files"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    storage_provider: Mapped[str] = mapped_column(String, nullable=False)
    bucket: Mapped[str] = mapped_column(String, nullable=False)
    file_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    original_name: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[MediaFileKind] = mapped_column(
        SQLAlchemyEnum(MediaFileKind, name="media_file_kind"),
        index=True,
        nullable=False,
    )
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
        index=True,
        nullable=True,
    )
    uploaded_by_admin_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("admin_accounts.id"),
        index=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
