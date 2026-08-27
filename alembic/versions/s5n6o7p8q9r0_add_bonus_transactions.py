"""add bonus_transactions

Бонусная программа: append-only реестр начислений и списаний. Баланс клиента
нигде не хранится — он считается как SUM(amount) по этой таблице.

Revision ID: s5n6o7p8q9r0
Revises: r4m5n6o7p8q9
"""

import sqlalchemy as sa
from alembic import op

revision = "s5n6o7p8q9r0"
down_revision = "r4m5n6o7p8q9"
branch_labels = None
depends_on = None


BONUS_TRANSACTION_TYPE = sa.Enum(
    "ORDER_ACCRUAL",
    "ORDER_SPEND",
    "ORDER_SPEND_REFUND",
    "ADMIN_ACCRUAL",
    "ADMIN_WITHDRAWAL",
    name="bonus_transaction_type",
)


def upgrade() -> None:
    bind = op.get_bind()
    BONUS_TRANSACTION_TYPE.create(bind, checkfirst=True)

    op.create_table(
        "bonus_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", BONUS_TRANSACTION_TYPE, nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"]),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"]),
        sa.ForeignKeyConstraint(["admin_account_id"], ["admin_accounts.id"]),
    )
    op.create_index("ix_bonus_transactions_user_id", "bonus_transactions", ["user_id"])
    op.create_index("ix_bonus_transactions_type", "bonus_transactions", ["type"])
    op.create_index(
        "ix_bonus_transactions_reservation_id", "bonus_transactions", ["reservation_id"]
    )
    op.create_index("ix_bonus_transactions_rental_id", "bonus_transactions", ["rental_id"])


def downgrade() -> None:
    op.drop_index("ix_bonus_transactions_rental_id", table_name="bonus_transactions")
    op.drop_index("ix_bonus_transactions_reservation_id", table_name="bonus_transactions")
    op.drop_index("ix_bonus_transactions_type", table_name="bonus_transactions")
    op.drop_index("ix_bonus_transactions_user_id", table_name="bonus_transactions")
    op.drop_table("bonus_transactions")
    BONUS_TRANSACTION_TYPE.drop(op.get_bind(), checkfirst=True)
