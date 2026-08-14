"""add franchise fields to admin_accounts and telegram subscribers

Добавляет роль `franchise` и привязку админ-аккаунта к городу:

* `admin_accounts.city_id` — город франшизы (NULL у super_admin/operator);
* `admin_accounts.is_active` — выключатель доступа;
* `admin_accounts.last_login_at`, `admin_accounts.created_at` — для статистики;
* `telegram_admin_subscribers.city_id` — адресация уведомлений по городу
  (NULL = глобальный подписчик, получает всё).

Revision ID: n0i1j2k3l4m5
Revises: m9h0i1j2k3l4
Create Date: 2026-08-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "n0i1j2k3l4m5"
down_revision = "m9h0i1j2k3l4"
branch_labels = None
depends_on = None


# (таблица, колонка, тип, nullable, server_default)
_NEW_COLUMNS = (
    ("admin_accounts", "city_id", sa.Uuid(), True, None),
    ("admin_accounts", "is_active", sa.Boolean(), False, sa.true()),
    ("admin_accounts", "last_login_at", sa.DateTime(timezone=True), True, None),
    ("admin_accounts", "created_at", sa.DateTime(timezone=True), True, None),
    ("telegram_admin_subscribers", "city_id", sa.Uuid(), True, None),
)

# Enum-типы роли: `admin_account_role` хранит values ("super_admin"),
# `admin_role` в legacy-таблице admin_users — имена ("SUPER_ADMIN").
_ROLE_ENUMS = (
    ("admin_account_role", "franchise", "FRANCHISE", ("super_admin", "operator")),
    ("admin_role", "FRANCHISE", "franchise", ("SUPER_ADMIN", "OPERATOR")),
)


def _existing_columns(inspector, table: str) -> set[str]:
    try:
        return {column["name"] for column in inspector.get_columns(table)}
    except Exception:
        # Таблицы может не быть на очень старой базе — её создаст
        # `Base.metadata.create_all` сразу с нужными колонками.
        return set()


def _add_role_enum_labels(bind) -> None:
    for type_name, preferred, fallback, preferred_markers in _ROLE_ENUMS:
        rows = bind.execute(
            sa.text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = :type_name"
            ),
            {"type_name": type_name},
        ).all()
        existing = {row[0] for row in rows}
        if not existing:
            # Типа нет — создаст SQLAlchemy при create_all.
            continue
        if preferred in existing or fallback in existing:
            continue
        label = preferred if existing & set(preferred_markers) else fallback
        op.execute(sa.text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{label}'"))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, column, type_, nullable, server_default in _NEW_COLUMNS:
        existing = _existing_columns(inspector, table)
        if not existing or column in existing:
            continue
        op.add_column(
            table,
            sa.Column(column, type_, nullable=nullable, server_default=server_default),
        )

    if bind.dialect.name != "postgresql":
        return

    _add_role_enum_labels(bind)

    # FK и индексы добавляем только на Postgres: SQLite не умеет
    # ALTER TABLE ADD CONSTRAINT, а батч-режим ради dev-базы избыточен.
    for table, constraint in (
        ("admin_accounts", "admin_accounts_city_id_fkey"),
        ("telegram_admin_subscribers", "telegram_admin_subscribers_city_id_fkey"),
    ):
        if "city_id" not in _existing_columns(sa.inspect(bind), table):
            continue
        op.execute(
            sa.text(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{constraint}') THEN "
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                "FOREIGN KEY (city_id) REFERENCES cities(id); "
                "END IF; END $$;"
            )
        )
        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_city_id ON {table} (city_id)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()

    for table, column, *_ in reversed(_NEW_COLUMNS):
        if column not in _existing_columns(sa.inspect(bind), table):
            continue
        op.drop_column(table, column)
    # Значения enum в Postgres не удаляем — это разрушительная операция.
