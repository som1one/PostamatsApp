"""add document name to verification requests

Revision ID: 9f3c1e2b7a11
Revises: 7c2a8e1f9b44
Create Date: 2026-05-01 14:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9f3c1e2b7a11"
down_revision = "7c2a8e1f9b44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "verification_requests",
        sa.Column("document_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("verification_requests", "document_name")
