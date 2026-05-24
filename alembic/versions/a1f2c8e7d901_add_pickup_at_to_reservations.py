"""add pickup_at to reservations

Revision ID: a1f2c8e7d901
Revises: 8a7c2d1e5b90
Create Date: 2026-05-22 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a1f2c8e7d901"
down_revision = "8a7c2d1e5b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reservations",
        sa.Column("pickup_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reservations", "pickup_at")
