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
    ACTIVE_RETURN_REQUEST_STATUSES,
    generate_return_deadline,
    get_active_return_request_for_rental,
    serialize_return_request_payload,
)

# Юниты в этих статусах физически лежат в своей ячейке. RENTED/LOST/RETIRED
# ячейку не занимают, даже если locker_cell_id ещё не обнулён (stale reference).
_PHYSICALLY_PRESENT_UNIT_STATUSES = (
    InventoryStatus.AVAILABLE,
    InventoryStatus.RESERVED,
    InventoryStatus.RETURN_PENDING,
    InventoryStatus.AWAITING_CONFIRMATION,
    InventoryStatus.MAINTENANCE,
    InventoryStatus.DAMAGED,
)


class ReturnRequestError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


async def _find_home_return_cell(
    db: AsyncSession,
    *,
    unit: InventoryUnit,
    locker_id: UUID,
) -> LockerCell | None:
    """«Родная» ячейка: та, из которой товар забрали при выдаче.

    Товар должен возвращаться в свою ячейку, поэтому она проверяется
    первой. Берём её только если она пригодна прямо сейчас:
    - статус VACANT, либо OCCUPIED без юнита внутри («сталый» статус
      после ручных правок/рассинхрона с ESI — физически ячейка пуста);
    - в ней не числится другой физически присутствующий юнит;
    - на неё не смотрит чужой активный возврат (иначе мы перезапишем
      его PIN на постамате);
    - supports_return и не FAULT/DISABLED/RESERVED/OPENED.
    Если ячейка непригодна — вернём None, и сработает общий подбор.
    """
    last_pickup_move = (
        await db.scalars(
            select(InventoryMovement)
            .where(
                InventoryMovement.inventory_unit_id == unit.id,
                InventoryMovement.from_locker_id == locker_id,
                InventoryMovement.from_cell_id.is_not(None),
                InventoryMovement.to_status == InventoryStatus.RENTED,
            )
            .order_by(InventoryMovement.created_at.desc())
            .limit(1)
        )
    ).first()
    if last_pickup_move is None or last_pickup_move.from_cell_id is None:
        return None

    cell = await db.get(LockerCell, last_pickup_move.from_cell_id)
    if (
        cell is None
        or cell.locker_id != locker_id
        or not cell.supports_return
        or cell.status not in (LockerCellStatus.VACANT, LockerCellStatus.OCCUPIED)
    ):
        return None

    other_unit_inside = (
        await db.scalars(
            select(InventoryUnit.id)
            .where(
                InventoryUnit.locker_cell_id == cell.id,
                InventoryUnit.id != unit.id,
                InventoryUnit.status.in_(_PHYSICALLY_PRESENT_UNIT_STATUSES),
            )
            .limit(1)
        )
    ).first()
    if other_unit_inside is not None:
        return None

    foreign_return = (
        await db.scalars(
            select(ReturnRequest.id)
            .where(
                ReturnRequest.cell_id == cell.id,
                ReturnRequest.status.in_(ACTIVE_RETURN_REQUEST_STATUSES),
            )
            .limit(1)
        )
    ).first()
    if foreign_return is not None:
        return None

    if cell.status == LockerCellStatus.OCCUPIED:
        # «Сталый» OCCUPIED принимаем, только если после нашей выдачи в эту
        # ячейку не оформляли НИКАКОЙ возврат — даже проваленный. Провал
        # заявки не гарантирует, что товар не положили физически (вебхук
        # закрытия мог потеряться), а открывать дверцу над чужим товаром
        # нельзя. Настоящие фантомные OCCUPIED (рассинхрон с ESI без
        # каких-либо возвратов) этот фильтр не задевает.
        later_return = (
            await db.scalars(
                select(ReturnRequest.id)
                .where(
                    ReturnRequest.cell_id == cell.id,
                    ReturnRequest.requested_at >= last_pickup_move.created_at,
                )
                .limit(1)
            )
        ).first()
        if later_return is not None:
            return None

    return cell


async def _find_legacy_return_cell(
    db: AsyncSession,
    *,
    unit: InventoryUnit,
    locker_id: UUID,
) -> LockerCell | None:
    _PHYSICALLY_PRESENT_STATUSES = (
        InventoryStatus.AVAILABLE,
        InventoryStatus.RESERVED,
        InventoryStatus.RETURN_PENDING,
        InventoryStatus.AWAITING_CONFIRMATION,
        InventoryStatus.MAINTENANCE,
        InventoryStatus.DAMAGED,
    )
    occupied_cell_ids_subq = (
        select(InventoryUnit.locker_cell_id)
        .where(
            InventoryUnit.locker_cell_id.is_not(None),
            InventoryUnit.id != unit.id,
            InventoryUnit.status.in_(_PHYSICALLY_PRESENT_STATUSES),
        )
        .subquery()
    )
    # Ячейки под чужими активными возвратами не трогаем — там уже
    # выставлен чужой PIN на постамате.
    active_return_cells_subq = (
        select(ReturnRequest.cell_id)
        .where(ReturnRequest.status.in_(ACTIVE_RETURN_REQUEST_STATUSES))
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
            LockerCell.id.not_in(select(active_return_cells_subq)),
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

    # Приоритет 1: «родная» ячейка — товар возвращается туда, откуда его
    # забрали при выдаче. При возврате в другой постамат (разрешён в рамках
    # города) движения выдачи там нет, и поиск сам вернёт None.
    cell = await _find_home_return_cell(db, unit=unit, locker_id=return_locker_id)

    if cell is None:
        # Приоритет 2: любая реально пустая ячейка — статус VACANT и в ней
        # не висит `InventoryUnit` с "физически присутствующим" статусом.
        # Юниты со статусом RENTED/LOST/RETIRED не занимают ячейку физически,
        # даже если locker_cell_id ещё не обнулён (stale reference).
        # Ячейки под чужими активными возвратами исключаем даже если их
        # статус в БД VACANT (рассинхрон) — иначе перезапишем чужой PIN.
        occupied_cell_ids_subq = (
            select(InventoryUnit.locker_cell_id)
            .where(
                InventoryUnit.locker_cell_id.is_not(None),
                InventoryUnit.status.in_(_PHYSICALLY_PRESENT_UNIT_STATUSES),
            )
            .subquery()
        )
        active_return_cells_subq = (
            select(ReturnRequest.cell_id)
            .where(ReturnRequest.status.in_(ACTIVE_RETURN_REQUEST_STATUSES))
            .subquery()
        )
        stmt = (
            select(LockerCell)
            .where(
                LockerCell.locker_id == return_locker_id,
                LockerCell.supports_return.is_(True),
                LockerCell.status == LockerCellStatus.VACANT,
                LockerCell.id.not_in(select(occupied_cell_ids_subq)),
                LockerCell.id.not_in(select(active_return_cells_subq)),
            )
            .order_by(LockerCell.label.asc().nulls_last(), LockerCell.created_at.asc())
            .limit(1)
        )
        cell = (await db.scalars(stmt)).first()
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
