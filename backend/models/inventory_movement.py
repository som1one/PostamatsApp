from uuid import UUID, uuid4

from sqlalchemy import Enum as SQLAlchemyEnum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import InventoryStatus


class InventoryMovement(Base, TimestampMixin):
    __tablename__ = "inventory_movements"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    inventory_unit_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("inventory_units.id"),
        index=True,
        nullable=False,
    )
    from_locker_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("locker_locations.id"),
        index=True,
        nullable=True,
    )
    to_locker_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("locker_locations.id"),
        index=True,
        nullable=True,
    )
    from_cell_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("locker_cells.id"),
        index=True,
        nullable=True,
    )
    to_cell_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("locker_cells.id"),
        index=True,
        nullable=True,
    )
    from_status: Mapped[InventoryStatus | None] = mapped_column(
        SQLAlchemyEnum(InventoryStatus, name="inventory_status"),
        nullable=True,
    )
    to_status: Mapped[InventoryStatus | None] = mapped_column(
        SQLAlchemyEnum(InventoryStatus, name="inventory_status"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_by_admin_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("admin_users.id"),
        index=True,
        nullable=True,
    )
    