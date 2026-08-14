"""Background scheduler that auto-confirms pickup for PICKUP_OPENED rentals.

If a rental cell was opened (status PICKUP_OPENED) and the user has not
confirmed pickup within AUTO_PICKUP_TIMEOUT_MINUTES (default 15 minutes),
the system automatically considers the item picked up and transitions the
rental to ACTIVE.

Runs every RENTAL_AUTO_PICKUP_INTERVAL_SECONDS seconds (default 30).
"""
import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    RentalEventSource,
    RentalStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.utils.inventory_tracking import add_inventory_movement
from backend.utils.reservation_utils import calculate_planned_end_at

logger = logging.getLogger(__name__)

# Через сколько минут после открытия ячейки считать товар изъятым.
AUTO_PICKUP_TIMEOUT_MINUTES = 15

# Частота проверки (секунды).
RENTAL_AUTO_PICKUP_INTERVAL_SECONDS = 30


async def auto_confirm_opened_pickups() -> None:
    """Find PICKUP_OPENED rentals where cell was opened > 15 min ago and auto-confirm."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=AUTO_PICKUP_TIMEOUT_MINUTES)

    async with SessionLocal() as db:
        stmt = select(Rental).where(
            Rental.status == RentalStatus.PICKUP_OPENED,
            Rental.cell_opened_at.is_not(None),
            Rental.cell_opened_at <= cutoff,
        )
        rentals = list((await db.scalars(stmt)).all())
        if not rentals:
            return

        confirmed = 0
        for rental in rentals:
            try:
                prev_rental_status = rental.status

                unit = await db.get(InventoryUnit, rental.inventory_unit_id)
                cell = (
                    await db.get(LockerCell, unit.locker_cell_id)
                    if unit is not None and unit.locker_cell_id is not None
                    else None
                )
                prev_unit_status = unit.status if unit is not None else None
                prev_cell_id = unit.locker_cell_id if unit is not None else None

                rental.status = RentalStatus.ACTIVE
                # Аренда стартует сейчас (момент авто-подтверждения).
                rental.starts_at = now

                # Пересчитываем planned_end_at от фактического старта.
                if rental.reservation_id is not None:
                    reservation = await db.get(Reservation, rental.reservation_id)
                    if reservation is not None:
                        rental.planned_end_at = calculate_planned_end_at(
                            now,
                            reservation.duration_type,
                            reservation.duration_value,
                        )

                if unit is not None:
                    unit.status = InventoryStatus.RENTED
                    unit.locker_cell_id = None

                if cell is not None:
                    cell.status = LockerCellStatus.VACANT
                    cell.last_closed_at = now
                    cell.last_event_at = now

                if unit is not None:
                    add_inventory_movement(
                        db,
                        unit=unit,
                        from_locker_id=rental.pickup_locker_id,
                        to_locker_id=None,
                        from_cell_id=prev_cell_id,
                        to_cell_id=None,
                        from_status=prev_unit_status,
                        to_status=InventoryStatus.RENTED,
                        reason="auto_pickup_confirmed",
                    )

                db.add(
                    RentalEvent(
                        rental_id=rental.id,
                        event_type="auto_pickup_confirmed",
                        from_status=prev_rental_status,
                        to_status=RentalStatus.ACTIVE,
                        source=RentalEventSource.SYSTEM,
                        payload_json={
                            "trigger": "auto_pickup_timeout",
                            "timeoutMinutes": AUTO_PICKUP_TIMEOUT_MINUTES,
                            "cellOpenedAt": rental.cell_opened_at.isoformat()
                            if rental.cell_opened_at
                            else None,
                        },
                    )
                )
                confirmed += 1
            except Exception:
                logger.exception(
                    "Error auto-confirming pickup for rental %s", rental.id
                )

        if confirmed:
            try:
                await db.commit()
                logger.info(
                    "Auto-confirmed pickup for %d rental(s) after %d-minute timeout",
                    confirmed,
                    AUTO_PICKUP_TIMEOUT_MINUTES,
                )
            except Exception:
                await db.rollback()
                logger.exception("Failed to commit auto-pickup batch")


def rental_auto_pickup_worker(
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    try:
        asyncio.run_coroutine_threadsafe(auto_confirm_opened_pickups(), loop).result()
        while not stop_event.wait(RENTAL_AUTO_PICKUP_INTERVAL_SECONDS):
            asyncio.run_coroutine_threadsafe(
                auto_confirm_opened_pickups(), loop
            ).result()
    except Exception:
        logger.exception("Rental auto-pickup scheduler stopped unexpectedly")


def start_rental_auto_pickup_scheduler(
    loop: asyncio.AbstractEventLoop,
) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    worker = threading.Thread(
        target=rental_auto_pickup_worker,
        args=(loop, stop_event),
        name="rental-auto-pickup-scheduler",
        daemon=True,
    )
    worker.start()
    return worker, stop_event


async def stop_rental_auto_pickup_scheduler(
    worker: threading.Thread | None,
    stop_event: threading.Event | None,
) -> None:
    if worker is None or stop_event is None:
        return
    stop_event.set()
    await asyncio.to_thread(worker.join, 5)
