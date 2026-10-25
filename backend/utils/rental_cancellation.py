"""Отмена аренды, которую ещё не забрали из постамата (PICKUP_READY).

Сюда ведут три пути: клиент отменяет заранее
(``POST /me/rentals/{id}/cancel-before-pickup``), шедулер снимает аренду,
не забранную за три часа (``rental_pickup_expiry``), и оператор жмёт
«Снять аренду» в админке. Во всех трёх вещь остаётся лежать в ячейке, а
деньги клиенту возвращаются.

Две вещи, которые раньше делались по-разному или не делались вовсе:

- ячейка остаётся «занята»: вещь внутри. Раньше шедулер и админка ставили
  ей «пусто», и оператор мог положить туда вторую вещь;
- код ячейки в постамате меняется на новый, никому не известный. Иначе
  клиент, которому уже вернули деньги, мог открыть ячейку старым PIN, и
  следующий арендатор нашёл бы её пустой.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    RentalEventSource,
    RentalStatus,
    ReturnRequestStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.return_request import ReturnRequest
from backend.utils.esi_client import sync_cell_state
from backend.utils.reservation_utils import generate_pickup_pin

logger = logging.getLogger(__name__)

_LIVE_PICKUP_STATUSES = (RentalStatus.PICKUP_READY, RentalStatus.PICKUP_OPENED)
_LIVE_RETURN_STATUSES = (
    ReturnRequestStatus.CREATED,
    ReturnRequestStatus.LOCKER_OPENED,
    ReturnRequestStatus.AWAITING_CLOSE,
)


async def release_unit_kept_in_cell(db: AsyncSession, rental: Rental, now) -> None:
    """Вещь снова доступна для брони, ячейка с ней — «занята»."""
    unit = await db.get(InventoryUnit, rental.inventory_unit_id)
    if unit is None:
        return
    if unit.status in (InventoryStatus.RESERVED, InventoryStatus.RENTED):
        unit.status = InventoryStatus.AVAILABLE
    if unit.locker_cell_id is None:
        return
    cell = await db.get(LockerCell, unit.locker_cell_id)
    if cell is not None and cell.status in (LockerCellStatus.RESERVED, LockerCellStatus.OPENED):
        cell.status = LockerCellStatus.OCCUPIED
        cell.last_event_at = now


def _fresh_pin(old_pin: str | None) -> str:
    # «0000» ставит раскладка вещи оператором — его не повторяем.
    while True:
        pin = generate_pickup_pin()
        if pin != old_pin and pin != "0000":
            return pin


async def _replace_pin(db: AsyncSession, rental: Rental) -> str:
    unit = await db.get(InventoryUnit, rental.inventory_unit_id)
    if unit is None or unit.locker_cell_id is None:
        return "skipped:item_not_in_cell"
    cell = await db.get(LockerCell, unit.locker_cell_id)
    if cell is None:
        return "skipped:cell_not_found"

    # Ячейку уже занял чужой код — новая бронь или возврат. Его не трогаем:
    # они сами назначили ячейке свой PIN.
    other_rental = await db.scalar(
        select(Rental.id)
        .join(InventoryUnit, InventoryUnit.id == Rental.inventory_unit_id)
        .where(
            InventoryUnit.locker_cell_id == cell.id,
            Rental.id != rental.id,
            Rental.status.in_(_LIVE_PICKUP_STATUSES),
        )
        .limit(1)
    )
    if other_rental is not None:
        return "skipped:cell_has_live_rental"
    live_return = await db.scalar(
        select(ReturnRequest.id)
        .where(ReturnRequest.cell_id == cell.id, ReturnRequest.status.in_(_LIVE_RETURN_STATUSES))
        .limit(1)
    )
    if live_return is not None:
        return "skipped:cell_has_live_return"

    # Только set-cell: состояние «занята» и новый код. Дверца не открывается.
    await sync_cell_state(
        db,
        locker_id=cell.locker_id,
        cell_id=cell.id,
        state="occupied",
        pin=_fresh_pin(rental.pickup_pin),
    )
    return "replaced"


async def reset_pin_after_pickup_cancel(db: AsyncSession, rental: Rental) -> str:
    """Меняет код ячейки отменённой аренды. Вызывать после коммита отмены.

    Не бросает: постамат может быть офлайн, а отмена и возврат денег уже
    состоялись. Итог пишется событием аренды ``pickup_pin_reset``.
    """
    # После rollback атрибуты объекта истекают, а ленивая загрузка в
    # асинхронной сессии падает — запоминаем всё нужное заранее.
    rental_id = rental.id
    status = rental.status
    try:
        outcome = await _replace_pin(db, rental)
    except Exception as exc:
        await db.rollback()
        logger.warning("Failed to reset pickup PIN for cancelled rental %s: %s", rental_id, exc)
        outcome = f"failed:{exc}"
    try:
        db.add(
            RentalEvent(
                rental_id=rental_id,
                event_type="pickup_pin_reset",
                from_status=status,
                to_status=status,
                source=RentalEventSource.SYSTEM,
                payload_json={"outcome": outcome},
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to record pickup PIN reset for rental %s", rental_id)
    return outcome
