"""add bonus_transactions

Бонусная программа: append-only реестр начислений и списаний. Баланс клиента
нигде не хранится — он считается как SUM(amount) по этой таблице.

Миграция написана так, чтобы её было безопасно прогнать поверх базы, где
таблица уже появилась из `Base.metadata.create_all` в `init_db()` — на проде
схему держит именно он, а не alembic (см. соседние миграции с тем же
`inspector.has_table`-guard).

Revision ID: s5n6o7p8q9r0
Revises: r4m5n6o7p8q9
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "s5n6o7p8q9r0"
down_revision = "r4m5n6o7p8q9"
branch_labels = None
depends_on = None


ENUM_NAME = "bonus_transaction_type"
ENUM_LABELS = (
    "ORDER_ACCRUAL",
    "ORDER_SPEND",
    "ORDER_SPEND_REFUND",
    "ADMIN_ACCRUAL",
    "ADMIN_WITHDRAWAL",
)


def _column_enum(bind):
    """Тип enum для колонки.

    На Postgres обязателен ``create_type=False``: сам тип мы создаём отдельно
    с ``checkfirst=True``, а ``create_table`` иначе попытается создать его
    второй раз уже без проверки и упадёт `DuplicateObject`, откатив всю
    миграцию.
    """
    if bind.dialect.name == "postgresql":
        return postgresql.ENUM(*ENUM_LABELS, name=ENUM_NAME, create_type=False)
    return sa.Enum(*ENUM_LABELS, name=ENUM_NAME)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*ENUM_LABELS, name=ENUM_NAME).create(bind, checkfirst=True)

    if inspector.has_table("bonus_transactions"):
        return

    op.create_table(
        "bonus_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", _column_enum(bind), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("rental_id", sa.Uuid(), nullable=True),
        sa.Column("admin_account_id", sa.Uuid(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"]),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"]),
        sa.ForeignKeyConstraint(["admin_account_id"], ["admin_accounts.id"]),
    )
    op.create_index(
        op.f("ix_bonus_transactions_user_id"), "bonus_transactions", ["user_id"]
    )
    op.create_index(op.f("ix_bonus_transactions_type"), "bonus_transactions", ["type"])
    op.create_index(
        op.f("ix_bonus_transactions_reservation_id"),
        "bonus_transactions",
        ["reservation_id"],
    )
    op.create_index(
        op.f("ix_bonus_transactions_rental_id"), "bonus_transactions", ["rental_id"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("bonus_transactions"):
        op.drop_index(op.f("ix_bonus_transactions_rental_id"), table_name="bonus_transactions")
        op.drop_index(
            op.f("ix_bonus_transactions_reservation_id"), table_name="bonus_transactions"
        )
        op.drop_index(op.f("ix_bonus_transactions_type"), table_name="bonus_transactions")
        op.drop_index(op.f("ix_bonus_transactions_user_id"), table_name="bonus_transactions")
        op.drop_table("bonus_transactions")

    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name=ENUM_NAME).drop(bind, checkfirst=True)
