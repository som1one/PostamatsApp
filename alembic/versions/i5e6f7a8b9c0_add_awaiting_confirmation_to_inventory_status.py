"""add awaiting_confirmation to inventory_status enum

Revision ID: i5e6f7a8b9c0
Revises: h4d5e6f7a8b9
Create Date: 2026-06-04 16:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "i5e6f7a8b9c0"
down_revision = "h4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    rows = bind.execute(
        sa.text(
            "SELECT enumlabel FROM pg_enum e "
            "JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = 'inventory_status'"
        )
    ).all()
    existing = {row[0] for row in rows}
    if "AWAITING_CONFIRMATION" in existing or "awaiting_confirmation" in existing:
        return

    uses_names = any(
        label in existing
        for label in ("AVAILABLE", "RESERVED", "RENTED", "RETURN_PENDING")
    )
    new_label = "AWAITING_CONFIRMATION" if uses_names else "awaiting_confirmation"
    op.execute(
        sa.text(
            "ALTER TYPE inventory_status ADD VALUE IF NOT EXISTS '%s'" % new_label
        )
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values with a simple ALTER TYPE.
    # Keep downgrade idempotent and leave the extra label in place.
    return
