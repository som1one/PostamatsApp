"""fix media_files uploaded_by_admin_id FK: admin_users -> admin_accounts

The media_files table was originally created via create_all() when the
FK pointed to admin_users.  The model was later changed to reference
admin_accounts, but the DB constraint was never updated.  This migration
drops the stale FK and recreates it targeting admin_accounts.

Revision ID: m9h0i1j2k3l4
Revises: l8g9h0i1j2k3
Create Date: 2026-06-13 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "m9h0i1j2k3l4"
down_revision = "l8g9h0i1j2k3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Drop the old FK that incorrectly points to admin_users.
    # The constraint name may vary — find it dynamically.
    result = bind.execute(sa.text("""
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'media_files'::regclass
          AND contype = 'f'
          AND EXISTS (
              SELECT 1
              FROM unnest(conkey) AS col_id
              JOIN pg_attribute a ON a.attrelid = conrelid AND a.attnum = col_id
              WHERE a.attname = 'uploaded_by_admin_id'
          )
    """))
    for row in result:
        constraint_name = row[0]
        op.drop_constraint(constraint_name, "media_files", type_="foreignkey")

    # Create the correct FK pointing to admin_accounts.
    op.create_foreign_key(
        "media_files_uploaded_by_admin_id_fkey",
        "media_files",
        "admin_accounts",
        ["uploaded_by_admin_id"],
        ["id"],
    )


def downgrade() -> None:
    # Revert: drop the admin_accounts FK, restore admin_users FK.
    op.drop_constraint(
        "media_files_uploaded_by_admin_id_fkey",
        "media_files",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "media_files_uploaded_by_admin_id_fkey",
        "media_files",
        "admin_users",
        ["uploaded_by_admin_id"],
        ["id"],
    )
