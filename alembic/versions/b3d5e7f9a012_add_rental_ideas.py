"""add rental ideas table and extend media_file_kind enum

Revision ID: b3d5e7f9a012
Revises: a1f2c8e7d901
Create Date: 2026-05-25 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b3d5e7f9a012"
down_revision = "a1f2c8e7d901"
branch_labels = None
depends_on = None


NEW_MEDIA_KIND = "rental_idea_photo"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Добавляем новое значение в существующий enum media_file_kind, если его ещё нет.
    # PostgreSQL 12+ поддерживает ALTER TYPE ... ADD VALUE IF NOT EXISTS внутри
    # транзакции; новое значение НЕ используется в этой же миграции, поэтому
    # ограничение "нельзя использовать в той же транзакции" нас не затрагивает.
    if bind.dialect.name == "postgresql":
        existing = bind.execute(
            sa.text(
                "SELECT 1 FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = 'media_file_kind' AND e.enumlabel = :label"
            ),
            {"label": NEW_MEDIA_KIND},
        ).first()
        if existing is None:
            op.execute(
                sa.text(
                    "ALTER TYPE media_file_kind ADD VALUE IF NOT EXISTS '%s'"
                    % NEW_MEDIA_KIND
                )
            )

    if not inspector.has_table("rental_ideas"):
        op.create_table(
            "rental_ideas",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("idea", sa.Text(), nullable=False),
            sa.Column("reference_url", sa.String(length=2048), nullable=True),
            sa.Column("photo_id", sa.Uuid(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["photo_id"], ["media_files.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_rental_ideas_email"),
            "rental_ideas",
            ["email"],
            unique=False,
        )
        op.create_index(
            op.f("ix_rental_ideas_created_at"),
            "rental_ideas",
            ["created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("rental_ideas"):
        op.drop_index(op.f("ix_rental_ideas_created_at"), table_name="rental_ideas")
        op.drop_index(op.f("ix_rental_ideas_email"), table_name="rental_ideas")
        op.drop_table("rental_ideas")

    # Удалить значение из postgres enum штатным ALTER TYPE нельзя.
    # Откат значения media_file_kind=rental_idea_photo не делаем, чтобы
    # downgrade оставался идемпотентным и безопасным.
