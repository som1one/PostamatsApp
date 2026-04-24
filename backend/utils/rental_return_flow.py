"""Инициация возврата товара: выбор return-ячейки, вызов ESI, смена статусов аренды."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import InventoryStatus, LockerStatus, LockerCellStatus, RentalEventSource, RentalStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.utils.esi_client import EsiReturnOpenError, esi_trigger_return_cell_open


class ReturnRequestError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


async def start_rental_return(
    db: AsyncSession,
    *,
    rental: Rental,
    return_locker_id: UUID,
) -> dict:
    if rental.status == RentalStatus.RETURN_IN_PROGRESS:
        raise ReturnRequestError("RETURN_ALREADY_IN_PROGRESS")

    if rental.status not in (RentalStatus.ACTIVE, RentalStatus.OVERDUE):
        raise ReturnRequestError("INVALID_RENTAL_STATUS")

    locker = (
        await db.execute(select(LockerLocation).where(LockerLocation.id == return_locker_id))
    ).scalar_one_or_none()
    if locker is None:
        raise ReturnRequestError("LOCKER_NOT_FOUND")
    if locker.status != LockerStatus.ONLINE:
        raise ReturnRequestError("LOCKER_OFFLINE")

    stmt = (
        select(LockerCell)
        .where(
            LockerCell.locker_id == return_locker_id,
            LockerCell.supports_return.is_(True),
            LockerCell.status == LockerCellStatus.VACANT,
        )
        .order_by(LockerCell.label.asc().nulls_last(), LockerCell.created_at.asc())
        .limit(1)
    )
    cell = (await db.scalars(stmt)).first()
    if cell is None:
        raise ReturnRequestError("RETURN_CELL_NOT_AVAILABLE")

    unit = (
        await db.execute(select(InventoryUnit).where(InventoryUnit.id == rental.inventory_unit_id))
    ).scalar_one_or_none()
    if unit is None:
        raise ReturnRequestError("INVENTORY_NOT_FOUND")

    now = datetime.now(timezone.utc)

    try:
        await esi_trigger_return_cell_open(
            db,
            locker_id=return_locker_id,
            cell_id=cell.id,
            rental_id=rental.id,
        )
    except EsiReturnOpenError as exc:
        code = exc.code
        if code in ("ESI_HTTP_ERROR", "ESI_OPEN_FAILED"):
            raise ReturnRequestError("ESI_OPEN_FAILED") from exc
        if code == "ESI_NOT_CONFIGURED":
            raise ReturnRequestError("ESI_NOT_CONFIGURED") from exc
        raise ReturnRequestError(code) from exc

    prev = rental.status
    rental.return_locker_id = return_locker_id
    rental.status = RentalStatus.RETURN_IN_PROGRESS
    unit.status = InventoryStatus.RETURN_PENDING

    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type="return_requested",
            from_status=prev,
            to_status=RentalStatus.RETURN_IN_PROGRESS,
            source=RentalEventSource.USER,
            payload_json={
                "returnLockerId": str(return_locker_id),
                "cellId": str(cell.id),
            },
        )
    )

    try:
        await db.commit()
        await db.refresh(rental)
        await db.refresh(cell)
    except Exception as exc:
        await db.rollback()
        raise ReturnRequestError("RETURN_REQUEST_FAILED") from exc

    label = (cell.label or "").strip() or str(cell.external_cell_id or cell.id)[:8]
    return {
        "rentalId": str(rental.id),
        "status": rental.status.value,
        "lockerId": str(return_locker_id),
        "cellLabel": label,
        "instructions": "Откройте ячейку и положите товар внутрь, затем закройте дверцу.",
    }
