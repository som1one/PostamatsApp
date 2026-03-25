from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import ConditionReportType


class ConditionReport(Base, TimestampMixin):
    __tablename__ = "condition_reports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    inventory_unit_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("inventory_units.id"),
        index=True,
        nullable=False,
    )
    rental_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("rentals.id"), index=True, nullable=True)
    report_type: Mapped[ConditionReportType] = mapped_column(
        SQLAlchemyEnum(ConditionReportType, name="condition_report_type"),
        index=True,
        nullable=False,
    )
    condition_grade: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=True)
    created_by_admin_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("admin_users.id"),
        index=True,
        nullable=True,
    )
    