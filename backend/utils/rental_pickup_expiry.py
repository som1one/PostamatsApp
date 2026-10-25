"""Background scheduler that cancels stale PICKUP_READY rentals.

Runs every RENTAL_PICKUP_EXPIRY_INTERVAL_SECONDS seconds (default 60).
If a rental has status PICKUP_READY and pickup_expires_at <= now,
it is cancelled:
  - деньги клиенту   → refund списанного (или cancel холда)
  - inventory unit → AVAILABLE
  - locker cell    → OCCUPIED (вещь так и лежит внутри) + новый PIN в
                     постамате, чтобы старый код клиента не открывал ячейку
  - rental.status  → CANCELLED
  - rental.cancel_reason → "pickup_expired"
  - RentalEvent logged

Возврат денег обязателен: клиент уже заплатил, а товар так и не получил.
Раньше этот проход просто закрывал аренду, и деньги оставались у нас —
в отличие от ручной отмены до забора и от экспирации оплаченной брони,
где возврат делается.
"""
import asyncio
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.enums import RentalEventSource, RentalStatus
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.utils.payment_flow import release_reservation_payment
from backend.utils.rental_cancellation import (
    release_unit_kept_in_cell,
    reset_pin_after_pickup_cancel,
)

logger = logging.getLogger(__name__)

RENTAL_PICKUP_EXPIRY_INTERVAL_SECONDS = 60


async def expire_stale_pickup_rentals() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        stmt = select(Rental.id).where(
            Rental.status == RentalStatus.PICKUP_READY,
            Rental.pickup_expires_at.is_not(None),
            Rental.pickup_expires_at <= now,
        )
        rental_ids = list((await db.scalars(stmt)).all())
        if not rental_ids:
            return

        cancelled = 0
        # Коммитим каждую аренду отдельно: в проходе есть обращение к ЮKassa,
        # и падение на одной аренде не должно откатывать уже сделанные
        # возвраты по другим.
        for rental_id in rental_ids:
            try:
                rental = await db.get(Rental, rental_id)
                if rental is None or rental.status != RentalStatus.PICKUP_READY:
                    continue

                # Деньги возвращаем ДО отмены. Если ЮKassa недоступна, аренду
                # не закрываем — она попадёт в следующий тик. Подержать товар
                # в ячейке дешевле, чем оставить клиента без вещи и без денег.
                if rental.reservation_id is not None:
                    released = await release_reservation_payment(
                        db,
                        rental.reservation_id,
                        now,
                        context="pickup-expired rental",
                    )
                    if not released:
                        await db.rollback()
                        continue

                prev_status = rental.status

                # Вещь так и лежит в ячейке: юнит снова доступен, ячейка занята.
                await release_unit_kept_in_cell(db, rental, now)

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
                await db.commit()
                cancelled += 1
                # Старый PIN клиента больше не должен открывать ячейку.
                await reset_pin_after_pickup_cancel(db, rental)
            except Exception:
                await db.rollback()
                logger.exception("Error expiring pickup-ready rental %s", rental_id)

        if cancelled:
            logger.info("Cancelled %d stale pickup-ready rental(s)", cancelled)


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
