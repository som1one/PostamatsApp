"""add admin_edited_fields

Какие поля товара, города и фильтра товара поправили в админке — их
синхронизация каталога при выкладке больше не затирает
(``backend/utils/admin_edits.py``).

Как и соседние миграции, безопасна поверх базы, где колонки уже добавил
ручной DDL ``_ADMIN_EDIT_COLUMNS`` в ``backend/core/database.py``.

Revision ID: u7p8q9r0s1t2
Revises: t6o7p8q9r0s1
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "u7p8q9r0s1t2"
down_revision = "t6o7p8q9r0s1"
branch_labels = None
depends_on = None

TABLES = ("products", "cities", "product_filters")


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    for table in TABLES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "admin_edited_fields" not in columns:
            op.add_column(table, sa.Column("admin_edited_fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    for table in TABLES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "admin_edited_fields" in columns:
            op.drop_column(table, "admin_edited_fields")
