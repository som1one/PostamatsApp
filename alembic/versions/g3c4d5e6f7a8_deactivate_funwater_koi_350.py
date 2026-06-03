"""deactivate funwater koi 350

Revision ID: g3c4d5e6f7a8
Revises: f2b3c4d5e6f7
Create Date: 2026-06-01 17:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "g3c4d5e6f7a8"
down_revision = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set is_active=False for Funwater Koi 350
    op.execute(
        sa.text("UPDATE products SET is_active = false WHERE name ILIKE '%Funwater Koi 350%';")
    )


def downgrade() -> None:
    # Set is_active=True back for Funwater Koi 350
    op.execute(
        sa.text("UPDATE products SET is_active = true WHERE name ILIKE '%Funwater Koi 350%';")
    )
