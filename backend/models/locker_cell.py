from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum as SQLAlchemyEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import LockerCellStatus


class LockerCell(Base, TimestampMixin):
    __tablename__ = "locker_cells"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    locker_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("locker_locations.id"),
        index=True,
        nullable=False,
    )
    external_cell_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    size: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[LockerCellStatus] = mapped_column(
        SQLAlchemyEnum(LockerCellStatus, name="locker_cell_status"),
        default=LockerCellStatus.VACANT,
        index=True,
        nullable=False,
    )
    supports_return: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
