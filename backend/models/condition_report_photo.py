from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin


class ConditionReportPhoto(Base, TimestampMixin):
    __tablename__ = "condition_report_photos"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    condition_report_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("condition_reports.id"),
        index=True,
        nullable=False,
    )
    file_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("media_files.id"), index=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    