"""add admin accounts and sessions

Revision ID: 4b6f9f2c1a77
Revises: 24e818342461
Create Date: 2026-04-02 15:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "4b6f9f2c1a77"
down_revision: Union[str, None] = "24e818342461"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    admin_account_role = postgresql.ENUM(
        "super_admin",
        "operator",
        name="admin_account_role",
    )
    admin_account_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "admin_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("login", sa.String(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "super_admin",
                "operator",
                name="admin_account_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_accounts_login"), "admin_accounts", ["login"], unique=True)

    op.create_table(
        "admin_auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_account_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(), nullable=False),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["admin_account_id"], ["admin_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_auth_sessions_admin_account_id"),
        "admin_auth_sessions",
        ["admin_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_auth_sessions_expires_at"),
        "admin_auth_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_auth_sessions_refresh_token_hash"),
        "admin_auth_sessions",
        ["refresh_token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admin_auth_sessions_refresh_token_hash"),
        table_name="admin_auth_sessions",
    )
    op.drop_index(
        op.f("ix_admin_auth_sessions_expires_at"),
        table_name="admin_auth_sessions",
    )
    op.drop_index(
        op.f("ix_admin_auth_sessions_admin_account_id"),
        table_name="admin_auth_sessions",
    )
    op.drop_table("admin_auth_sessions")
    op.drop_index(op.f("ix_admin_accounts_login"), table_name="admin_accounts")
    op.drop_table("admin_accounts")
    postgresql.ENUM(name="admin_account_role").drop(op.get_bind(), checkfirst=True)
