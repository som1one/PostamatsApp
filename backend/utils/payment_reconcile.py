"""Фоновая сверка «висящих» платежей с ЮKassa.

Сценарий бага (жалоба клиента 2026-08-19): человек оплатил бронь, деньги
списались, но сайт продолжал показывать кнопку «Оплатить» и таймер «До
отмены брони», а через два часа бронь отменилась бы вообще без возврата.

Почему так выходило: статус платежа в нашей БД обновлялся только из двух
мест — уведомления ЮKassa (которое отбрасывалось проверкой Basic-авторизации,
которой у ЮKassa нет) и поллинга на странице /payment/return. Если клиент
платил через СБП или приложение банка и не возвращался в ту же вкладку,
платёж навсегда оставался PENDING, а бронь — AWAITING_PAYMENT.

Этот sweep закрывает дыру независимо от вебхуков: раз в тик берёт все
незавершённые платежи с provider_payment_id и спрашивает их настоящий статус
у ЮKassa. Оплаченный платёж переводит бронь в PAYMENT_AUTHORIZED и продлевает
её срок — дальше её подхватывает auto_confirm и превращает в аренду.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.models.enums import PaymentStatus, PaymentType, ReservationStatus
from backend.models.payment import Payment
from backend.models.reservation import Reservation
from backend.utils.payment_flow import sync_payment_with_provider
from backend.utils.reservation_utils import ensure_utc

logger = logging.getLogger(__name__)

# Платежу дают минуту «дозреть»: свежие обычно закрывает сам /payment/return,
# а лишние запросы в API ЮKassa ни к чему.
PAYMENT_RECONCILE_MIN_AGE_SECONDS = 60

# Старше суток не проверяем: неоплаченная ссылка ЮKassa к этому моменту
# протухла, а бронь давно закрыта.
PAYMENT_RECONCILE_MAX_AGE_HOURS = 24

# Предохранитель от лавины запросов, если в БД внезапно много висяков.
PAYMENT_RECONCILE_BATCH_LIMIT = 50

_UNSETTLED_STATUSES = (
    PaymentStatus.CREATED,
    PaymentStatus.PENDING,
    PaymentStatus.AUTHORIZED,
)


async def reconcile_pending_payments() -> None:
    now = datetime.now(timezone.utc)
    cutoff_new = now - timedelta(seconds=PAYMENT_RECONCILE_MIN_AGE_SECONDS)
    cutoff_old = now - timedelta(hours=PAYMENT_RECONCILE_MAX_AGE_HOURS)

    async with SessionLocal() as db:
        stmt = (
            select(Payment)
            .where(
                Payment.type == PaymentType.PREAUTH,
                Payment.status.in_(_UNSETTLED_STATUSES),
                Payment.provider_payment_id.is_not(None),
                Payment.created_at <= cutoff_new,
                Payment.created_at >= cutoff_old,
            )
            .order_by(Payment.created_at.asc())
            .limit(PAYMENT_RECONCILE_BATCH_LIMIT)
        )
        payments = list((await db.scalars(stmt)).all())
        if not payments:
            return

        recovered = 0
        for payment in payments:
            try:
                changed = await sync_payment_with_provider(db, payment, now=now)
                if not changed:
                    continue
                await db.commit()
                recovered += 1
                logger.info(
                    "Reconciled payment %s with YooKassa: status=%s reservation=%s",
                    payment.id,
                    payment.status.value,
                    payment.reservation_id,
                )
            except Exception:
                await db.rollback()
                logger.exception("Failed to reconcile payment %s", payment.id)

        if recovered:
            logger.info("Reconciled %d stale payment(s) with YooKassa", recovered)


async def reconcile_reservation_payments(
    db,
    reservations: list[Reservation],
    *,
    min_age_seconds: int = 0,
) -> bool:
    """Сверяет с ЮKassa платежи перечисленных «неоплаченных» броней.

    Не коммитит — транзакцией управляет вызывающий код. Возвращает True,
    если хоть один статус изменился.
    """
    targets = [
        r
        for r in reservations
        if r.status
        in (ReservationStatus.CREATED, ReservationStatus.AWAITING_PAYMENT)
    ]
    if not targets:
        return False

    now = datetime.now(timezone.utc)
    stmt = select(Payment).where(
        Payment.reservation_id.in_([r.id for r in targets]),
        Payment.type == PaymentType.PREAUTH,
        Payment.status.in_(_UNSETTLED_STATUSES),
        Payment.provider_payment_id.is_not(None),
    )
    changed = False
    for payment in (await db.scalars(stmt)).all():
        age = (now - ensure_utc(payment.created_at)).total_seconds()
        if age < min_age_seconds or age > PAYMENT_RECONCILE_MAX_AGE_HOURS * 3600:
            continue
        try:
            changed = await sync_payment_with_provider(db, payment, now=now) or changed
        except Exception:
            logger.exception("Payment %s reconciliation failed", payment.id)
    return changed


async def resolve_payment_before_release(db, reservation: Reservation) -> bool:
    """Последняя проверка перед тем, как отпустить неоплаченную бронь.

    Возвращает True, если оказалось, что бронь на самом деле оплачена (и
    статус уже поправлен в сессии) — тогда отменять/экспирировать её нельзя,
    иначе клиент останется без вещи и без денег. Не коммитит.
    """
    await reconcile_reservation_payments(db, [reservation])
    if reservation.status == ReservationStatus.PAYMENT_AUTHORIZED:
        logger.warning(
            "Reservation %s turned out to be paid — release aborted", reservation.id
        )
        return True
    return False
