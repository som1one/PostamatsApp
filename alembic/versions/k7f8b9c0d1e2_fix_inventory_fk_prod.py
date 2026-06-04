"""fix inventory fk prod

Revision ID: k7f8b9c0d1e2
Revises: j6f7a8b9c0d1
Create Date: 2026-06-04 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'k7f8b9c0d1e2'
down_revision = 'j6f7a8b9c0d1'
branch_labels = None
depends_on = None

def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute(
            '''
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'inventory_movements_performed_by_admin_id_fkey'
                    AND table_name = 'inventory_movements'
                ) THEN
                    ALTER TABLE inventory_movements DROP CONSTRAINT inventory_movements_performed_by_admin_id_fkey;
                END IF;
                
                ALTER TABLE inventory_movements ADD CONSTRAINT inventory_movements_performed_by_admin_id_fkey FOREIGN KEY (performed_by_admin_id) REFERENCES admin_accounts(id);
            END $$;
            '''
        )

def downgrade() -> None:
    pass
