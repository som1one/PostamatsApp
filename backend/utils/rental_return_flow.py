"""Return flow bootstrap: choose a cell, open it via ESI, persist a return request."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    RentalEventSource,
    RentalStatus,
    ReturnRequestStatus,
)
from backend.models.inventory_movement import InventoryMovement
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.return_request import ReturnRequest
from backend.utils.esi_client import EsiReturnOpenError, esi_trigger_return_cell_open
from backend.utils.reservation_utils import generate_pickup_pin
from backend.utils.return_requests import (
    generate_return_deadline,
    get_active_return_request_for_rental,
    serialize_return_request_payload,
)


class ReturnRequestError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


async def _find_legacy_return_cell(
    db: AsyncSession,
    *,
    unit: InventoryUnit,
    locker_id: UUID,
) -> LockerCell | None:
    occupied_cell_ids_subq = (
        select(InventoryUnit.locker_cell_id)
        .where(
            InventoryUnit.locker_cell_id.is_not(None),
            InventoryUnit.id != unit.id,
        )
        .subquery()
    )
    stmt = (
        select(LockerCell)
        .join(InventoryMovement, InventoryMovement.from_cell_id == LockerCell.id)
        .where(
            InventoryMovement.inventory_unit_id == unit.id,
            InventoryMovement.from_locker_id == locker_id,
            InventoryMovement.from_cell_id.is_not(None),
            InventoryMovement.to_status == InventoryStatus.RENTED,
            LockerCell.locker_id == locker_id,
            LockerCell.supports_return.is_(True),
            LockerCell.status.not_in((LockerCellStatus.FAULT, LockerCellStatus.DISABLED)),
            LockerCell.id.not_in(select(occupied_cell_ids_subq)),
        )
        .order_by(InventoryMovement.created_at.desc())
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


async def start_rental_return(
    db: AsyncSession,
    *,
    rental: Rental,
    return_locker_id: UUID,
) -> dict:
    if rental.status == RentalStatus.RETURN_IN_PROGRESS:
        active_request = await get_active_return_request_for_rental(db, rental.id)
        if active_request is None:
            raise ReturnRequestError("RETURN_ALREADY_IN_PROGRESS")
        return await serialize_return_request_payload(db, active_request)

    if rental.status not in (RentalStatus.ACTIVE, RentalStatus.OVERDUE):
        raise ReturnRequestError("INVALID_RENTAL_STATUS")

    active_request = await get_active_return_request_for_rental(db, rental.id)
    if active_request is not None:
        return await serialize_return_request_payload(db, active_request)

    locker = (
        await db.execute(select(LockerLocation).where(LockerLocation.id == return_locker_id))
    ).scalar_one_or_none()
    if locker is None:
        raise ReturnRequestError("LOCKER_NOT_FOUND")
    if locker.status != LockerStatus.ONLINE:
        raise ReturnRequestError("LOCKER_OFFLINE")

    unit = (
        await db.execute(select(InventoryUnit).where(InventoryUnit.id == rental.inventory_unit_id))
    ).scalar_one_or_none()
    if unit is None:
        raise ReturnRequestError("INVENTORY_NOT_FOUND")

    # Возврат разрешаем только в постамат того же города, где был получен товар.
    # Это защищает от ситуаций, когда пользователь случайно (или намеренно)
    # выбирает локер в другом городе через прямой API-вызов.
    if return_locker_id != rental.pickup_locker_id:
        pickup_locker = (
            await db.execute(
                select(LockerLocation).where(LockerLocation.id == rental.pickup_locker_id)
            )
        ).scalar_one_or_none()
        if pickup_locker is not None and pickup_locker.city_id != locker.city_id:
            raise ReturnRequestError("RETURN_LOCKER_DIFFERENT_CITY")

    # Берём VACANT-ячейку для возврата. Предпочитаем пустую (без юнитов).
    # Если таких нет — берём ячейку с AVAILABLE-юнитом (он будет вытеснен).
    occupied_cell_ids_subq = (
        select(InventoryUnit.locker_cell_id)
        .where(InventoryUnit.locker_cell_id.is_not(None))
        .subquery()
    )
    # Сначала пробуем полностью пустую ячейку
    stmt = (
        select(LockerCell)
        .where(
            LockerCell.locker_id == return_locker_id,
            LockerCell.supports_return.is_(True),
            LockerCell.status == LockerCellStatus.VACANT,
            LockerCell.id.not_in(select(occupied_cell_ids_subq)),
        )
        .order_by(LockerCell.label.asc().nulls_last(), LockerCell.created_at.asc())
        .limit(1)
    )
    cell = (await db.scalars(stmt)).first()

    # Если пустых нет — берём VACANT-ячейку, в которой есть только AVAILABLE-юнит
    if cell is None:
        available_only_cells_subq = (
            select(InventoryUnit.locker_cell_id)
            .where(
                InventoryUnit.locker_cell_id.is_not(None),
                InventoryUnit.status != InventoryStatus.AVAILABLE,
            )
            .subquery()
        )
        stmt_available = (
            select(LockerCell)
            .where(
                LockerCell.locker_id == return_locker_id,
                LockerCell.supports_return.is_(True),
                LockerCell.status == LockerCellStatus.VACANT,
                LockerCell.id.not_in(select(available_only_cells_subq)),
            )
            .order_by(LockerCell.label.asc().nulls_last(), LockerCell.created_at.asc())
            .limit(1)
        )
        cell = (await db.scalars(stmt_available)).first()

    if cell is None:
        legacy_cell = await _find_legacy_return_cell(
            db,
            unit=unit,
            locker_id=return_locker_id,
        )
        if legacy_cell is not None:
            cell = legacy_cell
        else:
            raise ReturnRequestError("RETURN_CELL_NOT_AVAILABLE")

    # Если в выбранной ячейке есть AVAILABLE-юнит — вытесняем его (отвязываем от ячейки).
    existing_unit_in_cell = (
        await db.scalars(
            select(InventoryUnit).where(
                InventoryUnit.locker_cell_id == cell.id,
                InventoryUnit.status == InventoryStatus.AVAILABLE,
            )
        )
    ).first()
    if existing_unit_in_cell is not None:
        existing_unit_in_cell.locker_cell_id = None

    now = datetime.now(timezone.utc)
    return_pin = generate_pickup_pin()
    deadline = generate_return_deadline(now)

    try:
        # Резервируем ячейку с PIN-кодом. Клиент сам введёт PIN
        # на клавиатуре постамата — дверца откроется.
        # Если постамат offline — пропускаем: пин записан в БД,
        # клиент введёт его когда постамат будет доступен.
        from backend.utils.esi_client import sync_cell_state, EsiOpenError
        await sync_cell_state(
            db,
            locker_id=return_locker_id,
            cell_id=cell.id,
            state="occupied",
            pin=return_pin,
        )
    except EsiOpenError as exc:
        code = str(exc)
        if code == "ESI_NOT_CONFIGURED":
            raise ReturnRequestError("ESI_NOT_CONFIGURED") from exc
        # ESI_MACHINE_OFFLINE, ESI_HTTP_ERROR — не блокируем возврат,
        # пин сохранён в БД и будет работать когда постамат online.
        import logging
        logging.getLogger(__name__).warning("ESI set-cell for return failed (non-blocking): %s", code)

    prev = rental.status
    rental.return_locker_id = return_locker_id
    rental.status = RentalStatus.RETURN_IN_PROGRESS
    unit.status = InventoryStatus.RETURN_PENDING
    cell.status = LockerCellStatus.RESERVED

    return_request = ReturnRequest(
        rental_id=rental.id,
        locker_id=return_locker_id,
        cell_id=cell.id,
        pin=return_pin,
        status=ReturnRequestStatus.CREATED,
        requested_at=now,
        deadline_at=deadline,
        opened_at=None,
    )
    db.add(return_request)

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
                "pin": return_pin,
                "expiresAt": deadline.isoformat(),
            },
        )
    )

    try:
        await db.commit()
        await db.refresh(return_request)
    except Exception as exc:
        await db.rollback()
        raise ReturnRequestError("RETURN_REQUEST_FAILED") from exc

    return await serialize_return_request_payload(db, return_request)
