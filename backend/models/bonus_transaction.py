from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Enum as SQLAlchemyEnum, ForeignKey, Numeric, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin
from backend.models.enums import BonusTransactionType


class BonusTransaction(Base, TimestampMixin):
    """Строка бонусного реестра. Таблица append-only: правок нет, только вставки.

    Баланс клиента нигде не хранится — он считается как SUM(amount) по этой
    таблице. Отдельная колонка-баланс была бы вторым источником правды и рано
    или поздно разошлась бы с реестром; объёмы тут такие, что индекса по
    `user_id` хватает с большим запасом.
    """

    __tablename__ = "bonus_transactions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    type: Mapped[BonusTransactionType] = mapped_column(
        SQLAlchemyEnum(BonusTransactionType, name="bonus_transaction_type"),
        index=True,
        nullable=False,
    )
    # Знаковая: «+» — начисление, «−» — списание.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    reservation_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("reservations.id"),
        index=True,
        nullable=True,
    )
    rental_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("rentals.id"),
        index=True,
        nullable=True,
    )
    admin_account_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("admin_accounts.id"),
        nullable=True,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
