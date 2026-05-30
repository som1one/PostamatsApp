"""add support chat tables

Revision ID: e1a2b3c4d5e6
Revises: d9e2b4f5c601
Create Date: 2026-06-10 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5e6"
down_revision: Union[str, None] = "d9e2b4f5c601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # NOTE: backend init_db() runs Base.metadata.create_all on startup, which may
    # already have created these tables/sequence/enums before this migration runs.
    # Guard every object so the migration is idempotent and a no-op when the
    # schema already exists (mirrors the pattern in earlier migrations).

    # Глобально монотонный ordering key для сообщений (Requirement 14.2).
    op.execute("CREATE SEQUENCE IF NOT EXISTS support_message_seq")

    conversation_status = postgresql.ENUM(
        "open",
        "in_progress",
        "closed",
        name="conversation_status",
    )
    conversation_status.create(bind, checkfirst=True)

    message_author_type = postgresql.ENUM(
        "client",
        "operator",
        name="message_author_type",
    )
    message_author_type.create(bind, checkfirst=True)

    if not inspector.has_table("support_conversations"):
        op.create_table(
            "support_conversations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "open",
                    "in_progress",
                    "closed",
                    name="conversation_status",
                    create_type=False,
                ),
                server_default="open",
                nullable=False,
            ),
            sa.Column("assigned_operator_id", sa.Uuid(), nullable=True),
            sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_message_seq", sa.BigInteger(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["assigned_operator_id"], ["admin_accounts.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_support_conversations_user_id"),
            "support_conversations",
            ["user_id"],
            unique=True,
        )
        op.create_index(
            op.f("ix_support_conversations_last_message_at"),
            "support_conversations",
            ["last_message_at"],
            unique=False,
        )

    if not inspector.has_table("support_messages"):
        op.create_table(
            "support_messages",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("conversation_id", sa.Uuid(), nullable=False),
            sa.Column("seq", sa.BigInteger(), nullable=False),
            sa.Column(
                "author_type",
                postgresql.ENUM(
                    "client",
                    "operator",
                    name="message_author_type",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column("author_user_id", sa.Uuid(), nullable=True),
            sa.Column("author_admin_id", sa.Uuid(), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["conversation_id"], ["support_conversations.id"]),
            sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["author_admin_id"], ["admin_accounts.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_support_messages_conversation_id"),
            "support_messages",
            ["conversation_id"],
            unique=False,
        )
        op.create_index(
            "ix_support_messages_conversation_seq",
            "support_messages",
            ["conversation_id", "seq"],
            unique=False,
        )

    if not inspector.has_table("support_conversation_reads"):
        op.create_table(
            "support_conversation_reads",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("conversation_id", sa.Uuid(), nullable=False),
            sa.Column("operator_id", sa.Uuid(), nullable=False),
            sa.Column(
                "last_read_seq",
                sa.BigInteger(),
                server_default="0",
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["conversation_id"], ["support_conversations.id"]),
            sa.ForeignKeyConstraint(["operator_id"], ["admin_accounts.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "conversation_id",
                "operator_id",
                name="uq_support_conversation_reads_conversation_operator",
            ),
        )
        op.create_index(
            op.f("ix_support_conversation_reads_conversation_id"),
            "support_conversation_reads",
            ["conversation_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_support_conversation_reads_operator_id"),
            "support_conversation_reads",
            ["operator_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("support_conversation_reads"):
        op.drop_index(
            op.f("ix_support_conversation_reads_operator_id"),
            table_name="support_conversation_reads",
        )
        op.drop_index(
            op.f("ix_support_conversation_reads_conversation_id"),
            table_name="support_conversation_reads",
        )
        op.drop_table("support_conversation_reads")

    if inspector.has_table("support_messages"):
        op.drop_index(
            "ix_support_messages_conversation_seq",
            table_name="support_messages",
        )
        op.drop_index(
            op.f("ix_support_messages_conversation_id"),
            table_name="support_messages",
        )
        op.drop_table("support_messages")

    if inspector.has_table("support_conversations"):
        op.drop_index(
            op.f("ix_support_conversations_last_message_at"),
            table_name="support_conversations",
        )
        op.drop_index(
            op.f("ix_support_conversations_user_id"),
            table_name="support_conversations",
        )
        op.drop_table("support_conversations")

    postgresql.ENUM(name="message_author_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="conversation_status").drop(bind, checkfirst=True)

    op.execute("DROP SEQUENCE IF EXISTS support_message_seq")
