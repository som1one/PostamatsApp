"""Background scheduler that expires stale reservations.

Runs every RESERVATION_EXPIRY_INTERVAL_SECONDS seconds (default 60).
Handles three statuses:
  - CREATED / AWAITING_PAYMENT  → marks EXPIRED, releases inventory (но только
    после финальной сверки платежа: «неоплаченная» бронь может оказаться
    оплаченной, если уведомление ЮKassa не дошло)
  - PAYMENT_AUTHORIZED          → возвращает деньги (refund списанных или
    cancel холда), затем marks EXPIRED
"""
import asyncio
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.enums import (
    InventoryStatus,
    PaymentStatus,
    PaymentType,
    ReservationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.payment import Payment
from backend.models.reservation import Reservation
from backend.utils.payment_reconcile import (
    reconcile_pending_payments,
    resolve_payment_before_release,
)
from backend.utils.reservation_auto_confirm import auto_confirm_paid_reservations
from backend.utils.yookassa_service import (
    cancel_yookassa_payment,
    refund_yookassa_payment,
)

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

        expired_count = 0
        for reservation in reservations:
            try:
                if reservation.status in _CANCELLABLE_WITHOUT_PAYMENT:
                    # Бронь числится неоплаченной — но уведомление ЮKassa
                    # могло не дойти. Спрашиваем провайдера напрямую, прежде
                    # чем забрать товар у клиента, который уже заплатил.
                    if await resolve_payment_before_release(db, reservation):
                        continue

                if reservation.status == ReservationStatus.PAYMENT_AUTHORIZED:
                    if not await _release_reservation_money(db, reservation, now):
                        # Деньги вернуть не удалось — бронь не закрываем,
                        # повторим на следующем тике. Держать товар в резерве
                        # дешевле, чем оставить клиента без вещи и без денег.
                        continue

                inventory_unit = await db.get(InventoryUnit, reservation.inventory_unit_id)
                if inventory_unit is not None and inventory_unit.status in (
                    InventoryStatus.RESERVED,
                ):
                    inventory_unit.status = InventoryStatus.AVAILABLE

                reservation.status = ReservationStatus.EXPIRED
                reservation.cancel_reason = "expired_by_scheduler"
                expired_count += 1
            except Exception:
                logger.exception("Error expiring reservation %s", reservation.id)

        try:
            await db.commit()
            logger.info("Expired %d stale reservation(s)", expired_count)
        except Exception:
            await db.rollback()
            logger.exception("Failed to commit reservation expiry batch")


async def _release_reservation_money(db, reservation: Reservation, now: datetime) -> bool:
    """Возвращает деньги клиенту перед экспирацией оплаченной брони.

    Схема оплаты одностадийная (capture=true), поэтому в норме платёж
    приходит в CAPTURED — деньги списаны, нужен refund. Двухстадийный
    AUTHORIZED (холд) отменяем через cancel. Раньше здесь искался только
    AUTHORIZED, и списанные деньги при экспирации не возвращались вовсе.

    False — деньги вернуть не удалось, бронь закрывать нельзя.
    """
    payment = (
        await db.scalars(
            select(Payment)
            .where(
                Payment.reservation_id == reservation.id,
                Payment.type == PaymentType.PREAUTH,
                Payment.status.in_((PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED)),
            )
            .limit(1)
        )
    ).first()
    if payment is None or not payment.provider_payment_id:
        return True

    is_captured = payment.status == PaymentStatus.CAPTURED
    try:
        if is_captured:
            await refund_yookassa_payment(
                payment.provider_payment_id,
                amount_value=payment.amount,
                currency=payment.currency or "RUB",
            )
            payment.status = PaymentStatus.REFUNDED
        else:
            await cancel_yookassa_payment(payment.provider_payment_id)
            payment.status = PaymentStatus.CANCELLED
        payment.processed_at = now
        return True
    except Exception:
        logger.exception(
            "Failed to %s Yookassa payment %s for expired reservation %s",
            "refund" if is_captured else "cancel",
            payment.provider_payment_id,
            reservation.id,
        )
        return False


async def _reservation_maintenance_tick() -> None:
    # Порядок важен. Сначала сверяем платежи с ЮKassa: бронь могла быть
    # оплачена, но уведомление не дошло — без сверки она выглядит как
    # неоплаченная и погибла бы в проходе экспирации вместе с деньгами.
    try:
        await reconcile_pending_payments()
    except Exception:
        logger.exception("Pending payment reconciliation sweep failed")
    # Затем спасаем оплаченные брони (продление expires_at + авто-confirm
    # в аренду), и только потом экспирация — иначе зависшая оплаченная
    # бронь могла бы быть отменена раньше, чем мы её продлим.
    try:
        await auto_confirm_paid_reservations()
    except Exception:
        logger.exception("Paid reservation auto-confirm sweep failed")
    await expire_stale_reservations()


def reservation_expiry_worker(
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    try:
        asyncio.run_coroutine_threadsafe(_reservation_maintenance_tick(), loop).result()
        while not stop_event.wait(RESERVATION_EXPIRY_INTERVAL_SECONDS):
            asyncio.run_coroutine_threadsafe(_reservation_maintenance_tick(), loop).result()
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
