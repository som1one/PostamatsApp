"""add city_id to max_admin_subscribers

Тот же признак, что и у telegram-подписчиков (миграция ``n0i1j2k3l4m5``):
``NULL`` — подписчик сети и получает все уведомления, заполненный город —
подписчик франшизы и получает только события своего города.

Отдельной миграцией, а не правкой ``o1j2k3l4m5n6``: та могла уже
примениться на живой базе.

Revision ID: p2k3l4m5n6o7
Revises: o1j2k3l4m5n6
Create Date: 2026-08-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "p2k3l4m5n6o7"
down_revision = "o1j2k3l4m5n6"
branch_labels = None
depends_on = None

_TABLE = "max_admin_subscribers"
_COLUMN = "city_id"


def _columns(bind) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return set()
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind)
    if not existing or _COLUMN in existing:
        # Таблицы ещё нет (её создаст create_all уже с колонкой) либо
        # колонка на месте — миграция идемпотентна.
        return

    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Uuid(), nullable=True))

    if bind.dialect.name != "postgresql":
        # SQLite не умеет ALTER TABLE ADD CONSTRAINT, а батч-режим ради
        # dev-базы избыточен: связь городов там проверять некому.
        return

    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = 'max_admin_subscribers_city_id_fkey') THEN "
            f"ALTER TABLE {_TABLE} ADD CONSTRAINT max_admin_subscribers_city_id_fkey "
            "FOREIGN KEY (city_id) REFERENCES cities(id); "
            "END IF; END $$;"
        )
    )
    op.execute(
        sa.text(
            f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_city_id ON {_TABLE} (city_id)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _COLUMN not in _columns(bind):
        return
    op.drop_column(_TABLE, _COLUMN)
