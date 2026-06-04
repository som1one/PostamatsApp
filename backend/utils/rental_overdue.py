import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, select

from backend.core.database import SessionLocal
from backend.core.settings import settings
from backend.models.enums import RentalEventSource, RentalStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.user import User
from backend.utils.telegram_bot import escape_html, notify_admins

logger = logging.getLogger(__name__)

RENTAL_OVERDUE_INTERVAL_SECONDS = 60
SUPPORT_OVERDUE_NOTIFICATION_DELAY = timedelta(hours=3)
SUPPORT_OVERDUE_NOTIFICATION_EVENT = "rental_overdue_support_notified"


def _ensure_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_dt(value: datetime | None) -> str:
    value = _ensure_aware_utc(value)
    if value is None:
        return "-"
    return value.astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y, %H:%M МСК")


def _format_duration(delta: timedelta) -> str:
    total_minutes = max(0, int(delta.total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


def _admin_rentals_link() -> str | None:
    base = settings.ADMIN_PANEL_URL
    if not base:
        return None
    return f"{base.rstrip('/')}/?section=rentals"


def _build_overdue_notification_text(
    *,
    rental: Rental,
    locker: LockerLocation,
    product: Product,
    user: User,
    now: datetime,
) -> str:
    overdue_from = _ensure_aware_utc(rental.overdue_started_at) or _ensure_aware_utc(
        rental.planned_end_at
    )
    overdue_for = _format_duration(now - overdue_from) if overdue_from else "-"
    return "\n".join(
        [
            "⚠️ <b>Просрочка аренды больше 3 часов</b>",
            f"Постамат: <b>{escape_html(locker.name)}</b>",
            f"Адрес: {escape_html(locker.address)}",
            f"Товар: {escape_html(product.name)}",
            f"Клиент: {escape_html(user.phone)}",
            f"Аренда: <code>{rental.id}</code>",
            f"Плановый возврат: {_format_dt(rental.planned_end_at)}",
            f"Просрочка: {escape_html(overdue_for)}",
        ]
    )


async def notify_support_about_long_overdue_rentals() -> None:
    now = datetime.now(timezone.utc)
    threshold = now - SUPPORT_OVERDUE_NOTIFICATION_DELAY
    buttons = []
    link = _admin_rentals_link()
    if link:
        buttons.append(("Открыть аренды", link))

    async with SessionLocal() as db:
        already_notified = exists().where(
            RentalEvent.rental_id == Rental.id,
            RentalEvent.event_type == SUPPORT_OVERDUE_NOTIFICATION_EVENT,
        )
        stmt = (
            select(Rental, LockerLocation, Product, User)
            .join(LockerLocation, Rental.pickup_locker_id == LockerLocation.id)
            .join(InventoryUnit, Rental.inventory_unit_id == InventoryUnit.id)
            .join(Product, InventoryUnit.product_id == Product.id)
            .join(User, Rental.user_id == User.id)
            .where(
                Rental.status == RentalStatus.OVERDUE,
                func.coalesce(Rental.overdue_started_at, Rental.planned_end_at) <= threshold,
                ~already_notified,
            )
        )
        rows = list((await db.execute(stmt)).all())
        if not rows:
            return

        for rental, locker, product, user in rows:
            text = _build_overdue_notification_text(
                rental=rental,
                locker=locker,
                product=product,
                user=user,
                now=now,
            )
            try:
                await notify_admins(text, buttons=buttons)
            except Exception:
                logger.exception("Failed to notify support about overdue rental %s", rental.id)
                continue
            db.add(
                RentalEvent(
                    rental_id=rental.id,
                    event_type=SUPPORT_OVERDUE_NOTIFICATION_EVENT,
                    from_status=RentalStatus.OVERDUE,
                    to_status=RentalStatus.OVERDUE,
                    source=RentalEventSource.SYSTEM,
                    payload_json={
                        "notifiedAt": now.isoformat(),
                        "lockerId": str(locker.id),
                        "lockerName": locker.name,
                    },
                )
            )

        try:
            await db.commit()
            logger.info("Sent overdue support notification(s): %d", len(rows))
        except Exception:
            await db.rollback()
            logger.exception("Failed to commit overdue support notification events")


async def mark_overdue_rentals() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        stmt = select(Rental).where(
            Rental.status == RentalStatus.ACTIVE,
            Rental.planned_end_at <= now,
        )
        rentals = list((await db.scalars(stmt)).all())
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

    await notify_support_about_long_overdue_rentals()


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
