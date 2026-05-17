from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import InventoryStatus
from backend.models.inventory_movement import InventoryMovement
from backend.models.inventory_unit import InventoryUnit


def add_inventory_movement(
    db: AsyncSession,
    *,
    unit: InventoryUnit,
    from_locker_id: UUID | None,
    to_locker_id: UUID | None,
    from_cell_id: UUID | None,
    to_cell_id: UUID | None,
    from_status: InventoryStatus | None,
    to_status: InventoryStatus | None,
    reason: str,
    comment: str | None = None,
    performed_by_admin_id: UUID | None = None,
) -> None:
    db.add(
        InventoryMovement(
            inventory_unit_id=unit.id,
            from_locker_id=from_locker_id,
            to_locker_id=to_locker_id,
            from_cell_id=from_cell_id,
            to_cell_id=to_cell_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            comment=comment,
            performed_by_admin_id=performed_by_admin_id,
        )
    )
