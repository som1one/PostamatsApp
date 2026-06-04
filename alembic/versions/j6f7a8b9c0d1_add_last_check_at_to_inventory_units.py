"""add last_check_at to inventory_units

Revision ID: j6f7a8b9c0d1
Revises: i5e6f7a8b9c0
Create Date: 2026-06-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "j6f7a8b9c0d1"
down_revision = "i5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inventory_units",
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("inventory_units", "last_check_at")
