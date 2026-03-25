"""add auth tables

Revision ID: 24e818342461
Revises: 
Create Date: 2026-03-22 18:18:28.673006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '24e818342461'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    auth_platform = postgresql.ENUM(
        "ios",
        "android",
        "huawei",
        "web",
        "admin",
        name="auth_platform",
    )
    auth_verification_session_status = postgresql.ENUM(
        "pending",
        "verified",
        "expired",
        "failed",
        name="auth_verification_session_status",
    )

    auth_platform.create(op.get_bind(), checkfirst=True)
    auth_verification_session_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(), nullable=False),
        sa.Column(
            "platform",
            postgresql.ENUM(
                "ios",
                "android",
                "huawei",
                "web",
                "admin",
                name="auth_platform",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("device_name", sa.String(), nullable=True),
        sa.Column("app_version", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_auth_sessions_expires_at"), "auth_sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_auth_sessions_platform"), "auth_sessions", ["platform"], unique=False)
    op.create_index(
        op.f("ix_auth_sessions_refresh_token_hash"),
        "auth_sessions",
        ["refresh_token_hash"],
        unique=True,
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)

    op.create_table(
        "auth_verification_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "verified",
                "expired",
                "failed",
                name="auth_verification_session_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("request_ip", sa.String(), nullable=True),
        sa.Column("request_user_agent", sa.Text(), nullable=True),
        sa.Column("confirm_ip", sa.String(), nullable=True),
        sa.Column("confirm_user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_auth_verification_sessions_expires_at"),
        "auth_verification_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_verification_sessions_phone"),
        "auth_verification_sessions",
        ["phone"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_verification_sessions_status"),
        "auth_verification_sessions",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_auth_verification_sessions_status"), table_name="auth_verification_sessions")
    op.drop_index(op.f("ix_auth_verification_sessions_phone"), table_name="auth_verification_sessions")
    op.drop_index(op.f("ix_auth_verification_sessions_expires_at"), table_name="auth_verification_sessions")
    op.drop_table("auth_verification_sessions")

    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_refresh_token_hash"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_platform"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_expires_at"), table_name="auth_sessions")
    op.drop_table("auth_sessions")

    postgresql.ENUM(name="auth_verification_session_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="auth_platform").drop(op.get_bind(), checkfirst=True)
