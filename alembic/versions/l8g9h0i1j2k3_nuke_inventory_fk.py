"""nuke inventory fk

Revision ID: l8g9h0i1j2k3
Revises: k7f8b9c0d1e2
Create Date: 2026-06-04 20:35:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'l8g9h0i1j2k3'
down_revision = 'k7f8b9c0d1e2'
branch_labels = None
depends_on = None

def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute(
            '''
            DO $$
            DECLARE
                r RECORD;
            BEGIN
                -- 1. Drop any foreign keys from inventory_movements to admin_users
                FOR r IN (
                    SELECT conname
                    FROM pg_constraint c
                    JOIN pg_class t1 ON c.conrelid = t1.oid
                    JOIN pg_class t2 ON c.confrelid = t2.oid
                    WHERE t1.relname = 'inventory_movements'
                      AND t2.relname = 'admin_users'
                      AND c.contype = 'f'
                ) LOOP
                    EXECUTE 'ALTER TABLE inventory_movements DROP CONSTRAINT ' || quote_ident(r.conname);
                END LOOP;
                
                -- 2. Drop the specific target constraint if it exists
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'inventory_movements_performed_by_admin_id_fkey'
                    AND table_name = 'inventory_movements'
                ) THEN
                    ALTER TABLE inventory_movements DROP CONSTRAINT inventory_movements_performed_by_admin_id_fkey;
                END IF;
                
                -- 3. Recreate the correct constraint
                ALTER TABLE inventory_movements ADD CONSTRAINT inventory_movements_performed_by_admin_id_fkey FOREIGN KEY (performed_by_admin_id) REFERENCES admin_accounts(id);
            END $$;
            '''
        )

def downgrade() -> None:
    pass
