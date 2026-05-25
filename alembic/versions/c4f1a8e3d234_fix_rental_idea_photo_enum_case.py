"""Add RENTAL_IDEA_PHOTO (uppercase) to media_file_kind enum.

Базовый enum media_file_kind в БД хранит значения в верхнем регистре
(VERIFICATION_FRONT, PRODUCT_COVER и т.д.), потому что схема была
создана через Base.metadata.create_all() — а SQLAlchemy без
values_callable использует имена членов, а не value. Предыдущая
миграция b3d5e7f9a012 добавила значение rental_idea_photo (lowercase),
которое SQLAlchemy никогда не использует — в INSERT идёт RENTAL_IDEA_PHOTO.
Эта миграция добавляет правильный uppercase-вариант.

Revision ID: c4f1a8e3d234
Revises: b3d5e7f9a012
Create Date: 2026-05-25 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c4f1a8e3d234"
down_revision = "b3d5e7f9a012"
branch_labels = None
depends_on = None


NEW_MEDIA_KIND = "RENTAL_IDEA_PHOTO"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
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


def downgrade() -> None:
    # Удалить значение из postgres enum штатным ALTER TYPE нельзя,
    # downgrade оставляем no-op для безопасности.
    pass
