"""Auto-confirm for paid reservations stuck in PAYMENT_AUTHORIZED.

В нормальном сценарии страница /payment/return вызывает
POST /reservations/{id}/confirm через секунды после оплаты, и бронь
превращается в аренду (PICKUP_READY). Но возврат с оплаты хрупкий:
при оплате через СБП/приложение банка пользователь часто не возвращается
в тот же браузер, где лежит pendingCheckout, или confirm падает из-за
офлайна постамата. Такая бронь застревала в PAYMENT_AUTHORIZED и через
2 часа после создания отменялась шедулером с возвратом холда.

Этот sweep вызывается из тика reservation_expiry (раз в 60 секунд),
ДО прохода экспирации, и делает две вещи:

1. Продлевает expires_at оплаченной брони до конца дня выдачи
   (pickup_at + 24 ч, либо created_at + 24 ч, если pickup_at пуст) —
   страховка для броней, оплаченных до выкатки продления в местах
   смены статуса.
2. Пытается выполнить тот же переход, что и confirm-эндпоинт: PIN,
   резерв ячейки через ESI, создание Rental(PICKUP_READY), статус
   CONFIRMED. Если постамат офлайн или ESI недоступен — просто ждёт
   следующего тика.

Свежие брони (моложе AUTO_CONFIRM_MIN_AGE_SECONDS) не трогаем, чтобы
не гоняться с confirm-запросом фронта сразу после оплаты.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.enums import (
    LockerStatus,
    RentalEventSource,
    RentalStatus,
    ReservationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_location import LockerLocation
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.utils.esi_client import EsiReserveError, reserve_cell_with_pin
from backend.utils.reservation_utils import (
    calculate_paid_reservation_expires_at,
    calculate_pickup_expires_at,
    calculate_planned_end_at,
    ensure_utc,
    generate_pickup_pin,
)

logger = logging.getLogger(__name__)

# Не трогаем бронь первые полторы минуты после создания: в это время
# фронт сам делает confirm со страницы возврата с оплаты.
AUTO_CONFIRM_MIN_AGE_SECONDS = 90


async def auto_confirm_paid_reservations() -> None:
    now = datetime.now(timezone.utc)
    min_created = now - timedelta(seconds=AUTO_CONFIRM_MIN_AGE_SECONDS)

    async with SessionLocal() as db:
        stmt = select(Reservation).where(
            Reservation.status == ReservationStatus.PAYMENT_AUTHORIZED,
            Reservation.created_at <= min_created,
        )
        reservations = list((await db.scalars(stmt)).all())
        if not reservations:
            return

        # ── Шаг 1: продление. Коммитим отдельно, чтобы падение ESI на
        # шаге 2 не откатило продление и бронь не умерла в проходе
        # экспирации. ──
        extended = 0
        for reservation in reservations:
            deadline = calculate_paid_reservation_expires_at(reservation)
            if ensure_utc(reservation.expires_at) < deadline:
                reservation.expires_at = deadline
                extended += 1
        if extended:
            try:
                await db.commit()
                logger.info("Extended expires_at for %d paid reservation(s)", extended)
            except Exception:
                await db.rollback()
                logger.exception("Failed to commit paid reservation extension")
                return

        # ── Шаг 2: confirm. Каждая бронь в своей транзакции. ──
        for reservation in reservations:
            if ensure_utc(reservation.expires_at) <= now:
                # Продление не помогло (день выдачи прошёл) — оставляем
                # проходу экспирации: он отменит бронь и вернёт холд.
                continue
            try:
                await _confirm_reservation(db, reservation, now)
            except EsiReserveError as exc:
                await db.rollback()
                logger.warning(
                    "Auto-confirm: ESI reserve failed for reservation %s: %s (will retry)",
                    reservation.id,
                    exc,
                )
            except Exception:
                await db.rollback()
                logger.exception("Auto-confirm failed for reservation %s", reservation.id)


async def _confirm_reservation(db, reservation: Reservation, now: datetime) -> None:
    """Повторяет переход confirm-эндпоинта (routers/reservation.py)."""
    # Фронт мог успеть подтвердить параллельно — тогда rental уже есть.
    existing = (
        await db.scalars(
            select(Rental).where(Rental.reservation_id == reservation.id).limit(1)
        )
    ).first()
    if existing is not None:
        if reservation.status == ReservationStatus.PAYMENT_AUTHORIZED:
            reservation.status = ReservationStatus.CONFIRMED
            reservation.confirmed_at = now
            await db.commit()
        return

    locker = await db.get(LockerLocation, reservation.locker_id)
    if locker is None or locker.status != LockerStatus.ONLINE:
        # Постамат офлайн/не бронируем — подождём следующего тика.
        return

    inventory_unit = await db.get(InventoryUnit, reservation.inventory_unit_id)
    if inventory_unit is None or inventory_unit.locker_cell_id is None:
        logger.warning(
            "Auto-confirm: reservation %s has no inventory cell, skipping",
            reservation.id,
        )
        return

    pickup_pin = generate_pickup_pin()
    await reserve_cell_with_pin(
        db,
        locker_id=reservation.locker_id,
        cell_id=inventory_unit.locker_cell_id,
        pin=pickup_pin,
    )

    # Пока ходили в ESI, фронт мог успеть подтвердить бронь сам —
    # перечитываем статус, чтобы не создать вторую аренду.
    await db.refresh(reservation)
    if reservation.status != ReservationStatus.PAYMENT_AUTHORIZED:
        await db.rollback()
        return

    starts_at = (
        ensure_utc(reservation.pickup_at) if reservation.pickup_at is not None else now
    )
    rental = Rental(
        user_id=reservation.user_id,
        reservation_id=reservation.id,
        inventory_unit_id=reservation.inventory_unit_id,
        pickup_locker_id=reservation.locker_id,
        pickup_pin=pickup_pin,
        status=RentalStatus.PICKUP_READY,
        pickup_expires_at=(
            calculate_pickup_expires_at(now)
            if starts_at <= now
            else starts_at + timedelta(hours=24)
        ),
        starts_at=starts_at,
        planned_end_at=calculate_planned_end_at(
            starts_at,
            reservation.duration_type,
            reservation.duration_value,
        ),
    )
    reservation.status = ReservationStatus.CONFIRMED
    reservation.confirmed_at = now
    db.add(rental)
    await db.flush()
    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type="reservation_confirmed",
            from_status=None,
            to_status=RentalStatus.PICKUP_READY,
            source=RentalEventSource.SYSTEM,
            payload_json={
                "reservationId": str(reservation.id),
                "trigger": "auto_confirm_scheduler",
            },
        )
    )
    await db.commit()
    logger.info(
        "Auto-confirmed paid reservation %s into rental %s",
        reservation.id,
        rental.id,
    )
