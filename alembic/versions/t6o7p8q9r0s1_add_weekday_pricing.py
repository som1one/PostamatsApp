"""add weekday pricing

Цена по дням недели: наценка в процентах на каждый день недели
(``weekday_price_markups``) и галочка у товара, на который она действует
(``products.weekday_pricing_enabled``).

Как и соседние миграции, безопасна поверх базы, где схему уже достроил
``init_db()``: таблицу создаёт ``create_all``, колонку — ручной DDL
``_WEEKDAY_PRICING_COLUMNS`` в ``backend/core/database.py``.

Revision ID: t6o7p8q9r0s1
Revises: s5n6o7p8q9r0
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "t6o7p8q9r0s1"
down_revision = "s5n6o7p8q9r0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "weekday_pricing_enabled" not in product_columns:
        op.add_column(
            "products",
            sa.Column(
                "weekday_pricing_enabled",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
        )

    if inspector.has_table("weekday_price_markups"):
        return

    op.create_table(
        "weekday_price_markups",
        sa.Column("weekday", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("weekday"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("weekday_price_markups"):
        op.drop_table("weekday_price_markups")

    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "weekday_pricing_enabled" in product_columns:
        op.drop_column("products", "weekday_pricing_enabled")
