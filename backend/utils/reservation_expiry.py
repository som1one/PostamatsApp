"""Background scheduler that expires stale reservations.

Runs every RESERVATION_EXPIRY_INTERVAL_SECONDS seconds (default 60).
Handles three statuses:
  - CREATED / AWAITING_PAYMENT  → just marks EXPIRED, releases inventory
  - PAYMENT_AUTHORIZED          → cancels the Yookassa preauth, then marks EXPIRED
"""
import asyncio
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.enums import InventoryStatus, PaymentStatus, ReservationStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.payment import Payment
from backend.models.reservation import Reservation
from backend.utils.yookassa_service import cancel_yookassa_payment

logger = logging.getLogger(__name__)

RESERVATION_EXPIRY_INTERVAL_SECONDS = 60

_CANCELLABLE_WITHOUT_PAYMENT = (
    ReservationStatus.CREATED,
    ReservationStatus.AWAITING_PAYMENT,
)


async def expire_stale_reservations() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        stmt = select(Reservation).where(
            Reservation.expires_at <= now,
            Reservation.status.in_(
                (
                    ReservationStatus.CREATED,
                    ReservationStatus.AWAITING_PAYMENT,
                    ReservationStatus.PAYMENT_AUTHORIZED,
                )
            ),
        )
        reservations = list((await db.scalars(stmt)).all())
        if not reservations:
            return

        for reservation in reservations:
            try:
                if reservation.status == ReservationStatus.PAYMENT_AUTHORIZED:
                    payment = (
                        await db.scalars(
                            select(Payment)
                            .where(
                                Payment.reservation_id == reservation.id,
                                Payment.status == PaymentStatus.AUTHORIZED,
                            )
                            .limit(1)
                        )
                    ).first()
                    if payment is not None and payment.provider_payment_id:
                        try:
                            await cancel_yookassa_payment(payment.provider_payment_id)
                            payment.status = PaymentStatus.CANCELLED
                            payment.processed_at = now
                        except Exception:
                            logger.exception(
                                "Failed to cancel Yookassa payment %s for expired reservation %s",
                                payment.provider_payment_id,
                                reservation.id,
                            )

                inventory_unit = await db.get(InventoryUnit, reservation.inventory_unit_id)
                if inventory_unit is not None and inventory_unit.status in (
                    InventoryStatus.RESERVED,
                ):
                    inventory_unit.status = InventoryStatus.AVAILABLE

                reservation.status = ReservationStatus.EXPIRED
                reservation.cancel_reason = "expired_by_scheduler"
            except Exception:
                logger.exception("Error expiring reservation %s", reservation.id)

        try:
            await db.commit()
            logger.info("Expired %d stale reservation(s)", len(reservations))
        except Exception:
            await db.rollback()
            logger.exception("Failed to commit reservation expiry batch")


def reservation_expiry_worker(
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    try:
        asyncio.run_coroutine_threadsafe(expire_stale_reservations(), loop).result()
        while not stop_event.wait(RESERVATION_EXPIRY_INTERVAL_SECONDS):
            asyncio.run_coroutine_threadsafe(expire_stale_reservations(), loop).result()
    except Exception:
        logger.exception("Reservation expiry scheduler stopped unexpectedly")


def start_reservation_expiry_scheduler(
    loop: asyncio.AbstractEventLoop,
) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    worker = threading.Thread(
        target=reservation_expiry_worker,
        args=(loop, stop_event),
        name="reservation-expiry-scheduler",
        daemon=True,
    )
    worker.start()
    return worker, stop_event


async def stop_reservation_expiry_scheduler(
    worker: threading.Thread | None,
    stop_event: threading.Event | None,
) -> None:
    if worker is None or stop_event is None:
        return
    stop_event.set()
    await asyncio.to_thread(worker.join, 5)
