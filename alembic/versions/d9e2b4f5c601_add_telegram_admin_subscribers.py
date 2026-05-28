"""add telegram_admin_subscribers table

Revision ID: d9e2b4f5c601
Revises: c4f1a8e3d234
Create Date: 2026-05-28 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "d9e2b4f5c601"
down_revision = "c4f1a8e3d234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("telegram_admin_subscribers"):
        op.create_table(
            "telegram_admin_subscribers",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("username", sa.String(length=64), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=True),
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
                "username", name="uq_telegram_admin_subscribers_username"
            ),
        )
        op.create_index(
            op.f("ix_telegram_admin_subscribers_username"),
            "telegram_admin_subscribers",
            ["username"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("telegram_admin_subscribers"):
        op.drop_index(
            op.f("ix_telegram_admin_subscribers_username"),
            table_name="telegram_admin_subscribers",
        )
        op.drop_table("telegram_admin_subscribers")
