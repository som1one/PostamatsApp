"""make verification document numbers unique

Revision ID: c4aa7f2be991
Revises: 9f3c1e2b7a11
Create Date: 2026-05-01 15:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c4aa7f2be991"
down_revision = "9f3c1e2b7a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE verification_requests SET document_number = UPPER(TRIM(document_number))")
    op.create_unique_constraint(
        "uq_verification_requests_document_number",
        "verification_requests",
        ["document_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_verification_requests_document_number",
        "verification_requests",
        type_="unique",
    )
