"""add cell_opened_at to rentals

Revision ID: f2b3c4d5e6f7
Revises: e1a2b3c4d5e6
Create Date: 2026-06-01 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f2b3c4d5e6f7"
down_revision = "e1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rentals",
        sa.Column("cell_opened_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rentals", "cell_opened_at")
