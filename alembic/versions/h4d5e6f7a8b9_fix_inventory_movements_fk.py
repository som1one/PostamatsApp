"""fix inventory movements fk

Revision ID: h4d5e6f7a8b9
Revises: g3c4d5e6f7a8
Create Date: 2026-06-02 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "h4d5e6f7a8b9"
down_revision = "g3c4d5e6f7a8"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.drop_constraint("inventory_movements_performed_by_admin_id_fkey", "inventory_movements", type_="foreignkey")
    op.create_foreign_key(
        "inventory_movements_performed_by_admin_id_fkey",
        "inventory_movements",
        "admin_accounts",
        ["performed_by_admin_id"],
        ["id"],
    )

def downgrade() -> None:
    op.drop_constraint("inventory_movements_performed_by_admin_id_fkey", "inventory_movements", type_="foreignkey")
    op.create_foreign_key(
        "inventory_movements_performed_by_admin_id_fkey",
        "inventory_movements",
        "admin_users",
        ["performed_by_admin_id"],
        ["id"],
    )
