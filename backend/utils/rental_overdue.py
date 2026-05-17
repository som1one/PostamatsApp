import asyncio
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.enums import RentalEventSource, RentalStatus
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent

logger = logging.getLogger(__name__)

RENTAL_OVERDUE_INTERVAL_SECONDS = 60


async def mark_overdue_rentals() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        stmt = select(Rental).where(
            Rental.status == RentalStatus.ACTIVE,
            Rental.planned_end_at <= now,
        )
        rentals = list((await db.scalars(stmt)).all())
        if not rentals:
            return

        updated = 0
        for rental in rentals:
            prev = rental.status
            rental.status = RentalStatus.OVERDUE
            rental.overdue_started_at = rental.overdue_started_at or now
            db.add(
                RentalEvent(
                    rental_id=rental.id,
                    event_type="rental_overdue",
                    from_status=prev,
                    to_status=RentalStatus.OVERDUE,
                    source=RentalEventSource.SYSTEM,
                    payload_json=None,
                )
            )
            updated += 1

        if updated:
            try:
                await db.commit()
                logger.info("Marked %d rental(s) overdue", updated)
            except Exception:
                await db.rollback()
                logger.exception("Failed to commit overdue rental batch")


def rental_overdue_worker(
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    try:
        asyncio.run_coroutine_threadsafe(mark_overdue_rentals(), loop).result()
        while not stop_event.wait(RENTAL_OVERDUE_INTERVAL_SECONDS):
            asyncio.run_coroutine_threadsafe(mark_overdue_rentals(), loop).result()
    except Exception:
        logger.exception("Rental overdue scheduler stopped unexpectedly")


def start_rental_overdue_scheduler(
    loop: asyncio.AbstractEventLoop,
) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    worker = threading.Thread(
        target=rental_overdue_worker,
        args=(loop, stop_event),
        name="rental-overdue-scheduler",
        daemon=True,
    )
    worker.start()
    return worker, stop_event


async def stop_rental_overdue_scheduler(
    worker: threading.Thread | None,
    stop_event: threading.Event | None,
) -> None:
    if worker is None or stop_event is None:
        return
    stop_event.set()
    await asyncio.to_thread(worker.join, 5)
