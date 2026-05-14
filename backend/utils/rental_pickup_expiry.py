"""Background scheduler that cancels stale PICKUP_READY rentals.

Runs every RENTAL_PICKUP_EXPIRY_INTERVAL_SECONDS seconds (default 60).
If a rental has status PICKUP_READY and pickup_expires_at <= now,
it is cancelled:
  - inventory unit → AVAILABLE
  - locker cell    → VACANT  (if still RESERVED)
  - rental.status  → CANCELLED
  - rental.cancel_reason → "pickup_expired"
  - RentalEvent logged
"""
import asyncio
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.enums import InventoryStatus, LockerCellStatus, RentalEventSource, RentalStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent

logger = logging.getLogger(__name__)

RENTAL_PICKUP_EXPIRY_INTERVAL_SECONDS = 60


async def expire_stale_pickup_rentals() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        stmt = select(Rental).where(
            Rental.status == RentalStatus.PICKUP_READY,
            Rental.pickup_expires_at.is_not(None),
            Rental.pickup_expires_at <= now,
        )
        rentals = list((await db.scalars(stmt)).all())
        if not rentals:
            return

        cancelled = 0
        for rental in rentals:
            try:
                prev_status = rental.status

                # Освобождаем единицу инвентаря
                unit = await db.get(InventoryUnit, rental.inventory_unit_id)
                if unit is not None and unit.status in (
                    InventoryStatus.RESERVED,
                    InventoryStatus.RENTED,
                ):
                    unit.status = InventoryStatus.AVAILABLE
                    # Освобождаем ячейку постамата
                    if unit.locker_cell_id is not None:
                        cell = await db.get(LockerCell, unit.locker_cell_id)
                        if cell is not None and cell.status == LockerCellStatus.RESERVED:
                            cell.status = LockerCellStatus.VACANT

                rental.status = RentalStatus.CANCELLED
                rental.cancel_reason = "pickup_expired"
                rental.actual_end_at = now
                rental.completed_at = now

                db.add(
                    RentalEvent(
                        rental_id=rental.id,
                        event_type="pickup_expired",
                        from_status=prev_status,
                        to_status=RentalStatus.CANCELLED,
                        source=RentalEventSource.SYSTEM,
                        payload_json={"cancelReason": "pickup_expired"},
                    )
                )
                cancelled += 1
            except Exception:
                logger.exception("Error expiring pickup-ready rental %s", rental.id)

        if cancelled:
            try:
                await db.commit()
                logger.info("Cancelled %d stale pickup-ready rental(s)", cancelled)
            except Exception:
                await db.rollback()
                logger.exception("Failed to commit pickup rental expiry batch")


def rental_pickup_expiry_worker(
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    try:
        asyncio.run_coroutine_threadsafe(expire_stale_pickup_rentals(), loop).result()
        while not stop_event.wait(RENTAL_PICKUP_EXPIRY_INTERVAL_SECONDS):
            asyncio.run_coroutine_threadsafe(expire_stale_pickup_rentals(), loop).result()
    except Exception:
        logger.exception("Rental pickup expiry scheduler stopped unexpectedly")


def start_rental_pickup_expiry_scheduler(
    loop: asyncio.AbstractEventLoop,
) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    worker = threading.Thread(
        target=rental_pickup_expiry_worker,
        args=(loop, stop_event),
        name="rental-pickup-expiry-scheduler",
        daemon=True,
    )
    worker.start()
    return worker, stop_event


async def stop_rental_pickup_expiry_scheduler(
    worker: threading.Thread | None,
    stop_event: threading.Event | None,
) -> None:
    if worker is None or stop_event is None:
        return
    stop_event.set()
    await asyncio.to_thread(worker.join, 5)
