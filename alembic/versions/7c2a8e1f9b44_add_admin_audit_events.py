"""add admin audit events

Revision ID: 7c2a8e1f9b44
Revises: 4b6f9f2c1a77
Create Date: 2026-04-03 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7c2a8e1f9b44"
down_revision: Union[str, None] = "4b6f9f2c1a77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_account_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("payload_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["admin_account_id"], ["admin_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_audit_events_action"), "admin_audit_events", ["action"], unique=False)
    op.create_index(
        op.f("ix_admin_audit_events_admin_account_id"),
        "admin_audit_events",
        ["admin_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_audit_events_created_at"),
        "admin_audit_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_audit_events_resource_id"),
        "admin_audit_events",
        ["resource_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_audit_events_resource_id"), table_name="admin_audit_events")
    op.drop_index(op.f("ix_admin_audit_events_created_at"), table_name="admin_audit_events")
    op.drop_index(op.f("ix_admin_audit_events_admin_account_id"), table_name="admin_audit_events")
    op.drop_index(op.f("ix_admin_audit_events_action"), table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
