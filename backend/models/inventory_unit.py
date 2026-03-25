from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Enum as SQLAlchemyEnum, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import InventoryStatus


class InventoryUnit(Base, TimestampMixin):
    __tablename__ = "inventory_units"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("products.id"), index=True, nullable=False)
    locker_cell_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("locker_cells.id"),
        unique=True,
        nullable=True,
    )
    serial_number: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    barcode: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    status: Mapped[InventoryStatus] = mapped_column(
        SQLAlchemyEnum(InventoryStatus, name="inventory_status"),
        default=InventoryStatus.AVAILABLE,
        index=True,
        nullable=False,
    )
    condition_grade: Mapped[str | None] = mapped_column(String, nullable=True)
    condition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
