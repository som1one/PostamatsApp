"""add max_admin_subscribers table

Подписчики второго канала админских уведомлений — мессенджера MAX.
Схема повторяет ``telegram_admin_subscribers``, но идентификаторов
диалога два: MAX адресует сообщение либо ``chat_id``, либо ``user_id``,
и какой из них известен — зависит от апдейта, по которому подписчика
связали.

Revision ID: o1j2k3l4m5n6
Revises: n0i1j2k3l4m5
Create Date: 2026-08-14 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "o1j2k3l4m5n6"
down_revision = "n0i1j2k3l4m5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("max_admin_subscribers"):
        op.create_table(
            "max_admin_subscribers",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("username", sa.String(length=64), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=True),
            sa.Column("user_id", sa.BigInteger(), nullable=True),
            sa.Column(
                "is_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("note", sa.String(length=200), nullable=True),
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
            sa.UniqueConstraint(
                "username", name="uq_max_admin_subscribers_username"
            ),
        )
        op.create_index(
            op.f("ix_max_admin_subscribers_username"),
            "max_admin_subscribers",
            ["username"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("max_admin_subscribers"):
        op.drop_index(
            op.f("ix_max_admin_subscribers_username"),
            table_name="max_admin_subscribers",
        )
        op.drop_table("max_admin_subscribers")
