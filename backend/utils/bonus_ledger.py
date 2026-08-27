"""Бонусная программа: единственное место, где знают её правила.

Устройство: append-only реестр `bonus_transactions`, баланс = SUM(amount).
Начисление — 7% от суммы, реально списанной деньгами, в момент завершения
аренды. Списать бонусами можно не больше 90% заказа, поэтому картой всегда
остаётся оплатить хотя бы десятую часть и платежа на 0 ₽ не бывает.

Ни одна функция не коммитит — транзакцией управляет вызывающий код (тот же
контракт, что у `payment_flow`).
"""

import logging
from decimal import Decimal, ROUND_DOWN
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.bonus_transaction import BonusTransaction
from backend.models.enums import BonusTransactionType, PaymentStatus, PaymentType
from backend.models.payment import Payment
from backend.models.rental import Rental
from backend.models.reservation import Reservation
from backend.models.user import User
from backend.utils.lockers_utils import price_plan_to_minor_units

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


class BonusError(Exception):
    """Бонусную операцию выполнить нельзя. `code` уходит клиенту как detail."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _dialect_name(db: AsyncSession) -> str:
    try:
        return db.get_bind().dialect.name
    except Exception:
        return ""


def floor_to_ruble(value: Decimal) -> Decimal:
    """Округление вниз до целого рубля: 1 бонус = 1 ₽, копеек в бонусах нет."""

    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_DOWN)


async def get_balance(db: AsyncSession, user_id: UUID) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(BonusTransaction.amount), 0)).where(
            BonusTransaction.user_id == user_id
        )
    )
    return Decimal(total or 0).quantize(Decimal("0.01"))


async def _sum_by_type(
    db: AsyncSession,
    *,
    reservation_id: UUID,
    tx_type: BonusTransactionType,
) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(BonusTransaction.amount), 0)).where(
            BonusTransaction.reservation_id == reservation_id,
            BonusTransaction.type == tx_type,
        )
    )
    return Decimal(total or 0)


async def bonus_spent_for_reservation(db: AsyncSession, reservation_id: UUID) -> Decimal:
    """Сколько бонусов сейчас «висит» на брони: списано минус уже возвращено."""

    spent = -(await _sum_by_type(
        db, reservation_id=reservation_id, tx_type=BonusTransactionType.ORDER_SPEND
    ))
    returned = await _sum_by_type(
        db, reservation_id=reservation_id, tx_type=BonusTransactionType.ORDER_SPEND_REFUND
    )
    outstanding = spent - returned
    return outstanding if outstanding > ZERO else ZERO


async def bonus_accrued_for_rental(db: AsyncSession, rental_id: UUID) -> Decimal:
    """Сколько бонусов начислено за аренду — для карточки заказа."""

    total = await db.scalar(
        select(func.coalesce(func.sum(BonusTransaction.amount), 0)).where(
            BonusTransaction.rental_id == rental_id,
            BonusTransaction.type == BonusTransactionType.ORDER_ACCRUAL,
        )
    )
    return Decimal(total or 0)


def max_spendable_for_order(balance: Decimal, order_amount: Decimal) -> Decimal:
    """Потолок списания: меньшее из баланса и доли заказа, вниз до рубля."""

    share = Decimal(order_amount) * settings.BONUS_MAX_ORDER_SHARE_PERCENT / Decimal("100")
    cap = min(Decimal(balance), share)
    return floor_to_ruble(cap) if cap > ZERO else ZERO


async def max_spendable(
    db: AsyncSession,
    *,
    user_id: UUID,
    order_amount: Decimal,
) -> Decimal:
    balance = await get_balance(db, user_id)
    return max_spendable_for_order(balance, order_amount)


async def release_bonus_spend(db: AsyncSession, *, reservation_id: UUID) -> Decimal:
    """Возвращает клиенту бонусы, списанные за несостоявшийся заказ.

    Идемпотентна по построению: пишет строку только на разницу между списанным
    и уже возвращённым. Поэтому её безопасно звать из всех точек отмены —
    отмены брони, отмены аренды до выдачи и обоих шедулеров экспирации, — не
    выясняя, не сработала ли какая-то из них раньше.

    `preauth_amount` тут намеренно не трогаем: он остаётся историей того,
    сколько по этой брони реально списали картой, и поддержка видит в карточке
    аренды фактическую сумму, а не полную цену прайса.
    """
    outstanding = await bonus_spent_for_reservation(db, reservation_id)
    if outstanding <= ZERO:
        return ZERO

    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        return ZERO

    # `comment` у автоматических операций пустой намеренно: что произошло,
    # говорит `type`, а поле основания оставлено под то, что написал человек.
    db.add(
        BonusTransaction(
            user_id=reservation.user_id,
            type=BonusTransactionType.ORDER_SPEND_REFUND,
            amount=outstanding,
            reservation_id=reservation_id,
        )
    )
    # Сессии в проекте создаются с autoflush=False, а баланс считается
    # SQL-суммой — без явного flush следующий же расчёт в этой транзакции не
    # увидит только что добавленную строку. Коммита тут по-прежнему нет.
    await db.flush()
    logger.info(
        "Released %s bonus points for reservation %s", outstanding, reservation_id
    )
    return outstanding


async def apply_bonus_spend(
    db: AsyncSession,
    *,
    user: User,
    reservation: Reservation,
    amount: Decimal,
) -> Decimal:
    """Списывает бонусы в счёт брони и уменьшает сумму к оплате картой.

    Списанное фиксируется строкой реестра, а сумма к списанию с карты кладётся
    в `reservation.preauth_amount` — отдельной колонки под бонусы нет
    намеренно: миграции до прода не доезжают, а новая таблица создаётся сама.
    """
    amount = floor_to_ruble(Decimal(amount))
    if amount <= ZERO:
        return ZERO

    # Блокируем строку пользователя: два параллельных «Оплатить» не должны
    # списать один и тот же баланс дважды. На sqlite (dev, тесты) FOR UPDATE
    # не поддерживается — там конкуренции всё равно нет.
    if _dialect_name(db) == "postgresql":
        await db.execute(select(User.id).where(User.id == user.id).with_for_update())

    # Повторный клик «Оплатить» после неудачной оплаты не должен списать
    # бонусы второй раз: сначала снимаем прошлое списание по этой же брони.
    await release_bonus_spend(db, reservation_id=reservation.id)

    balance = await get_balance(db, user.id)
    limit = max_spendable_for_order(balance, reservation.quoted_amount)
    if amount > limit:
        raise BonusError("BONUS_AMOUNT_INVALID")

    db.add(
        BonusTransaction(
            user_id=user.id,
            type=BonusTransactionType.ORDER_SPEND,
            amount=-amount,
            reservation_id=reservation.id,
        )
    )
    reservation.preauth_amount = (reservation.quoted_amount - amount).quantize(Decimal("0.01"))
    await db.flush()
    return amount


async def _rental_cash_base(db: AsyncSession, rental: Rental) -> Decimal:
    """Сумма, реально оплаченная деньгами, — база для начисления процента."""

    if rental.reservation_id is None:
        return ZERO
    payment = (
        await db.scalars(
            select(Payment)
            .where(
                Payment.reservation_id == rental.reservation_id,
                Payment.type == PaymentType.PREAUTH,
                Payment.status.in_((PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED)),
            )
            .limit(1)
        )
    ).first()
    if payment is not None:
        return Decimal(payment.amount)

    # Платежа нет — так бывает в dev-stub режиме, где бронь подтверждают без
    # оплаты. Берём сумму, которую по брони и должны были списать картой.
    reservation = await db.get(Reservation, rental.reservation_id)
    if reservation is None:
        return ZERO
    return Decimal(reservation.preauth_amount or reservation.quoted_amount)


async def accrue_rental_bonus(db: AsyncSession, *, rental: Rental) -> Decimal:
    """Начисляет процент за завершённую аренду. Идемпотентна.

    Зовётся из всех трёх мест, где аренда становится COMPLETED (штатный
    возврат и два админских закрытия), поэтому обязана быть безопасной при
    повторном вызове.
    """
    existing = (
        await db.scalars(
            select(BonusTransaction.id)
            .where(
                BonusTransaction.rental_id == rental.id,
                BonusTransaction.type == BonusTransactionType.ORDER_ACCRUAL,
            )
            .limit(1)
        )
    ).first()
    if existing is not None:
        return ZERO

    base = await _rental_cash_base(db, rental)
    if base <= ZERO:
        return ZERO

    accrued = floor_to_ruble(base * settings.BONUS_ACCRUAL_PERCENT / Decimal("100"))
    if accrued <= ZERO:
        return ZERO

    db.add(
        BonusTransaction(
            user_id=rental.user_id,
            type=BonusTransactionType.ORDER_ACCRUAL,
            amount=accrued,
            rental_id=rental.id,
            reservation_id=rental.reservation_id,
        )
    )
    await db.flush()
    logger.info("Accrued %s bonus points for rental %s", accrued, rental.id)
    return accrued


async def admin_adjust(
    db: AsyncSession,
    *,
    user_id: UUID,
    amount: Decimal,
    direction: str,
    admin_account_id: UUID | None,
    comment: str,
) -> tuple[Decimal, Decimal]:
    """Ручное начисление или списание. Возвращает (сумма операции, новый баланс)."""

    amount = floor_to_ruble(Decimal(amount))
    if amount <= ZERO:
        raise BonusError("BONUS_AMOUNT_INVALID")

    normalized_comment = (comment or "").strip()
    if not normalized_comment:
        raise BonusError("BONUS_COMMENT_REQUIRED")

    balance = await get_balance(db, user_id)
    if direction == "withdraw":
        if amount > balance:
            raise BonusError("BONUS_INSUFFICIENT_BALANCE")
        signed = -amount
        tx_type = BonusTransactionType.ADMIN_WITHDRAWAL
    elif direction == "accrue":
        signed = amount
        tx_type = BonusTransactionType.ADMIN_ACCRUAL
    else:
        raise BonusError("BONUS_DIRECTION_INVALID")

    db.add(
        BonusTransaction(
            user_id=user_id,
            type=tx_type,
            amount=signed,
            admin_account_id=admin_account_id,
            comment=normalized_comment,
        )
    )
    await db.flush()
    return amount, (balance + signed).quantize(Decimal("0.01"))


async def list_transactions(
    db: AsyncSession,
    *,
    user_id: UUID,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[BonusTransaction], int]:
    total = await db.scalar(
        select(func.count(BonusTransaction.id)).where(BonusTransaction.user_id == user_id)
    )
    rows = (
        await db.scalars(
            select(BonusTransaction)
            .where(BonusTransaction.user_id == user_id)
            .order_by(BonusTransaction.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).all()
    return list(rows), int(total or 0)


def serialize_bonus_transaction(tx: BonusTransaction) -> dict:
    """Суммы — в минорных единицах, как во всём остальном API."""

    return {
        "id": str(tx.id),
        "type": tx.type.value,
        "amount": price_plan_to_minor_units(tx.amount, "RUB"),
        "comment": tx.comment,
        "rentalId": str(tx.rental_id) if tx.rental_id else None,
        "reservationId": str(tx.reservation_id) if tx.reservation_id else None,
        "createdAt": tx.created_at.isoformat() if tx.created_at else None,
    }
