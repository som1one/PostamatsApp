from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum as SQLAlchemyEnum, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import LockerStatus


class LockerLocation(Base, TimestampMixin):
    __tablename__ = "locker_locations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    city_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("cities.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    lon: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    status: Mapped[LockerStatus] = mapped_column(
        SQLAlchemyEnum(LockerStatus, name="locker_status"),
        default=LockerStatus.ONLINE,
        index=True,
        nullable=False,
    )
    working_hours_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    external_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    external_locker_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    partner_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
