from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    RentalEventSource,
    RentalStatus,
    ReturnRequestStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.return_request import ReturnRequest
from backend.utils.inventory_tracking import add_inventory_movement

ACTIVE_RETURN_REQUEST_STATUSES: tuple[ReturnRequestStatus, ...] = (
    ReturnRequestStatus.CREATED,
    ReturnRequestStatus.LOCKER_OPENED,
    ReturnRequestStatus.AWAITING_CLOSE,
)


def generate_return_deadline(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base + timedelta(seconds=settings.RETURN_REQUEST_TIMEOUT_SECONDS)


async def get_active_return_request_for_rental(
    db: AsyncSession,
    rental_id: UUID,
) -> ReturnRequest | None:
    stmt = (
        select(ReturnRequest)
        .where(
            ReturnRequest.rental_id == rental_id,
            ReturnRequest.status.in_(ACTIVE_RETURN_REQUEST_STATUSES),
        )
        .order_by(ReturnRequest.created_at.desc())
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


async def get_active_return_request_by_cell(
    db: AsyncSession,
    *,
    locker_id: UUID,
    cell_id: UUID,
) -> ReturnRequest | None:
    stmt = (
        select(ReturnRequest)
        .where(
            ReturnRequest.locker_id == locker_id,
            ReturnRequest.cell_id == cell_id,
            ReturnRequest.status.in_(ACTIVE_RETURN_REQUEST_STATUSES),
        )
        .order_by(ReturnRequest.created_at.desc())
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


async def serialize_return_request_payload(
    db: AsyncSession,
    request: ReturnRequest,
) -> dict:
    locker = await db.get(LockerLocation, request.locker_id)
    cell = await db.get(LockerCell, request.cell_id)
    label = ""
    if cell is not None:
        label = (cell.label or "").strip() or str(cell.external_cell_id or cell.id)[:8]
    return {
        "id": str(request.id),
        "rentalId": str(request.rental_id),
        "status": request.status.value,
        "lockerId": str(request.locker_id),
        "lockerName": locker.name if locker else None,
        "cellId": str(request.cell_id),
        "cellLabel": label,
        "pin": request.pin,
        "instructions": f"Введите PIN-код {request.pin} на клавиатуре постамата, положите товар в ячейку {label} и закройте дверцу.",
        "expiresAt": request.deadline_at.isoformat(),
    }


async def fail_return_request(
    db: AsyncSession,
    *,
    request: ReturnRequest,
    reason: str,
    source: RentalEventSource = RentalEventSource.SYSTEM,
) -> None:
    now = datetime.now(timezone.utc)
    rental = await db.get(Rental, request.rental_id)
    unit = await db.get(InventoryUnit, rental.inventory_unit_id) if rental else None
    cell = await db.get(LockerCell, request.cell_id)

    if request.status == ReturnRequestStatus.FAILED:
        return

    prev_rental_status = rental.status if rental else None
    request.status = ReturnRequestStatus.FAILED
    request.failure_reason = reason
    request.closed_at = request.closed_at or now
    if rental is not None and rental.status == RentalStatus.RETURN_IN_PROGRESS:
        rental.status = RentalStatus.INCIDENT
        rental.cancel_reason = reason
    if unit is not None:
        unit.status = InventoryStatus.RETURN_PENDING
    if cell is not None and cell.status in (
        LockerCellStatus.RESERVED,
        LockerCellStatus.OPENED,
    ):
        cell.status = LockerCellStatus.VACANT
        cell.last_closed_at = now
        cell.last_event_at = now

    if rental is not None:
        db.add(
            RentalEvent(
                rental_id=rental.id,
                event_type="return_incident",
                from_status=prev_rental_status,
                to_status=rental.status,
                source=source,
                payload_json={
                    "returnRequestId": str(request.id),
                    "reason": reason,
                },
            )
        )


async def complete_return_request(
    db: AsyncSession,
    *,
    request: ReturnRequest,
    provider_event_id: str | None,
    source: RentalEventSource,
) -> tuple[Rental | None, InventoryUnit | None]:
    now = datetime.now(timezone.utc)
    rental = await db.get(Rental, request.rental_id)
    if rental is None:
        return None, None
    unit = await db.get(InventoryUnit, rental.inventory_unit_id)
    cell = await db.get(LockerCell, request.cell_id)
    locker = await db.get(LockerLocation, request.locker_id)

    if request.status == ReturnRequestStatus.COMPLETED:
        return rental, unit

    prev_rental_status = rental.status
    prev_unit_status = unit.status if unit is not None else None
    prev_cell_id = unit.locker_cell_id if unit is not None else None
    prev_locker_id = None
    if prev_cell_id is not None:
        prev_cell = await db.get(LockerCell, prev_cell_id)
        prev_locker_id = prev_cell.locker_id if prev_cell is not None else None

    request.status = ReturnRequestStatus.COMPLETED
    request.provider_event_id = provider_event_id
    request.closed_at = request.closed_at or now
    request.completed_at = now

    rental.status = RentalStatus.COMPLETED
    rental.return_locker_id = request.locker_id
    rental.actual_end_at = now
    rental.completed_at = now
    rental.cancel_reason = None

    if unit is not None:
        unit.status = InventoryStatus.AWAITING_CONFIRMATION
        unit.locker_cell_id = request.cell_id

    if cell is not None:
        cell.status = LockerCellStatus.OCCUPIED
        cell.last_closed_at = now
        cell.last_event_at = now

    if unit is not None:
        add_inventory_movement(
            db,
            unit=unit,
            from_locker_id=prev_locker_id,
            to_locker_id=locker.id if locker is not None else request.locker_id,
            from_cell_id=prev_cell_id,
            to_cell_id=request.cell_id,
            from_status=prev_unit_status,
            to_status=InventoryStatus.AWAITING_CONFIRMATION,
            reason="return_awaiting_confirmation",
        )

    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type="return_completed",
            from_status=prev_rental_status,
            to_status=RentalStatus.COMPLETED,
            source=source,
            payload_json={
                "returnRequestId": str(request.id),
                "providerEventId": provider_event_id,
            },
        )
    )
    return rental, unit
