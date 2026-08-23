"""give franchise accounts several cities

Раньше у аккаунта франшизы был один ``admin_accounts.city_id``. Партнёр
часто держит соседний город, и второй аккаунт ради этого — лишний
перелогин. Города переезжают в связку ``admin_account_cities``, колонка
удаляется: два источника правды рано или поздно разъедутся.

Существующие франшизы получают ровно тот город, что был у них в колонке.

Revision ID: r4m5n6o7p8q9
Revises: q3l4m5n6o7p8
Create Date: 2026-08-15 21:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "r4m5n6o7p8q9"
down_revision = "q3l4m5n6o7p8"
branch_labels = None
depends_on = None


LINK_TABLE = "admin_account_cities"


def _columns(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table(LINK_TABLE):
        op.create_table(
            LINK_TABLE,
            sa.Column("admin_account_id", sa.Uuid(), nullable=False),
            sa.Column("city_id", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint(
                ["admin_account_id"], ["admin_accounts.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["city_id"], ["cities.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("admin_account_id", "city_id"),
        )
        op.create_index(
            "ix_admin_account_cities_city_id", LINK_TABLE, ["city_id"], unique=False
        )

    if "city_id" in _columns(bind, "admin_accounts"):
        op.execute(
            sa.text(
                f"INSERT INTO {LINK_TABLE} (admin_account_id, city_id) "
                "SELECT id, city_id FROM admin_accounts "
                "WHERE city_id IS NOT NULL "
                f"AND id NOT IN (SELECT admin_account_id FROM {LINK_TABLE})"
            )
        )
        # Индекс по колонке сносим руками: на SQLite batch пересоздаёт
        # таблицу и потом пытается вернуть отражённый индекс на уже
        # удалённую колонку.
        indexes = {
            index["name"] for index in inspect(bind).get_indexes("admin_accounts")
        }
        if "ix_admin_accounts_city_id" in indexes:
            op.drop_index("ix_admin_accounts_city_id", table_name="admin_accounts")
        with op.batch_alter_table("admin_accounts") as batch:
            batch.drop_column("city_id")


def downgrade() -> None:
    bind = op.get_bind()

    if "city_id" not in _columns(bind, "admin_accounts"):
        op.add_column(
            "admin_accounts", sa.Column("city_id", sa.Uuid(), nullable=True)
        )
        op.create_index(
            "ix_admin_accounts_city_id", "admin_accounts", ["city_id"], unique=False
        )
        # В одну колонку влезает только один город — берём первый попавшийся;
        # у мультигородских франшиз остальные города откат потеряет.
        op.execute(
            sa.text(
                "UPDATE admin_accounts SET city_id = ("
                f"SELECT city_id FROM {LINK_TABLE} "
                f"WHERE {LINK_TABLE}.admin_account_id = admin_accounts.id "
                "LIMIT 1)"
            )
        )

    if inspect(bind).has_table(LINK_TABLE):
        op.drop_index("ix_admin_account_cities_city_id", table_name=LINK_TABLE)
        op.drop_table(LINK_TABLE)
