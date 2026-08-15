"""rename rental_ideas to feedback_messages and add topic/source/phone/city

Раздел «Идеи» стал «Обратной связью»: в одну таблицу теперь стекаются все
обращения с публичных форм (идея для аренды, заявка на франшизу), а карточка
показывает тип обращения и клиент, из которого оно пришло.

Данные сохраняем: таблицу и колонку переименовываем, а не пересоздаём.
Старые строки — это идеи с сайта и из приложения; источник у них
неизвестен (клиент его не присылал), поэтому проставляем topic='idea',
source='unknown'.

Все изменения колонок идут одним ``batch_alter_table`` до переименования
таблицы: на SQLite каждый батч пересоздаёт таблицу, и дробить их на
несколько проходов (да ещё и по свежепереименованной таблице) — верный
способ потерять часть изменений.

Revision ID: q3l4m5n6o7p8
Revises: p2k3l4m5n6o7
Create Date: 2026-08-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "q3l4m5n6o7p8"
down_revision = "p2k3l4m5n6o7"
branch_labels = None
depends_on = None


OLD_TABLE = "rental_ideas"
NEW_TABLE = "feedback_messages"


def _index_names(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def _column_names(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _upgrade_columns(bind, table: str) -> None:
    columns = _column_names(bind, table)
    if not columns:
        return

    with op.batch_alter_table(table) as batch:
        if "idea" in columns and "message" not in columns:
            batch.alter_column(
                "idea",
                new_column_name="message",
                existing_type=sa.Text(),
                existing_nullable=False,
            )
        # server_default оставляем: он проставляет значения существующим
        # строкам и страхует прямые INSERT'ы мимо приложения. Приложение
        # всегда пишет topic/source явно.
        if "topic" not in columns:
            batch.add_column(
                sa.Column(
                    "topic",
                    sa.String(length=32),
                    nullable=False,
                    server_default="idea",
                )
            )
        if "source" not in columns:
            batch.add_column(
                sa.Column(
                    "source",
                    sa.String(length=32),
                    nullable=False,
                    server_default="unknown",
                )
            )
        if "phone" not in columns:
            batch.add_column(sa.Column("phone", sa.String(length=32), nullable=True))
        if "city" not in columns:
            batch.add_column(sa.Column("city", sa.String(length=120), nullable=True))
        # У заявки на франшизу email'а нет — снимаем NOT NULL.
        batch.alter_column(
            "email",
            existing_type=sa.String(length=255),
            nullable=True,
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table(NEW_TABLE):
        # Таблица уже переименована (например, база поднята из metadata) —
        # дотягиваем недостающие колонки.
        _upgrade_columns(bind, NEW_TABLE)
        if inspector.has_table(OLD_TABLE):
            # create_all успел создать пустую feedback_messages до миграции:
            # переносим обращения из старой таблицы, иначе они останутся
            # лежать в базе, но пропадут из админки.
            op.execute(
                sa.text(
                    f"INSERT INTO {NEW_TABLE} "
                    "(id, topic, source, name, email, message, reference_url, "
                    "photo_id, created_at) "
                    "SELECT id, 'idea', 'unknown', name, email, idea, "
                    f"reference_url, photo_id, created_at FROM {OLD_TABLE} "
                    f"WHERE id NOT IN (SELECT id FROM {NEW_TABLE})"
                )
            )
            op.drop_table(OLD_TABLE)
    elif inspector.has_table(OLD_TABLE):
        # Старые индексы висят на старом имени: сносим до переименования и
        # пересоздаём после — так имена остаются предсказуемыми.
        old_indexes = _index_names(bind, OLD_TABLE)
        for name in ("ix_rental_ideas_created_at", "ix_rental_ideas_email"):
            if name in old_indexes:
                op.drop_index(name, table_name=OLD_TABLE)
        _upgrade_columns(bind, OLD_TABLE)
        op.rename_table(OLD_TABLE, NEW_TABLE)
    else:
        # Чистая база: таблицы нет вовсе, создавать её здесь нечего.
        return

    indexes = _index_names(bind, NEW_TABLE)
    for name, column in (
        ("ix_feedback_messages_email", "email"),
        ("ix_feedback_messages_created_at", "created_at"),
        ("ix_feedback_messages_topic", "topic"),
    ):
        if name not in indexes:
            op.create_index(name, NEW_TABLE, [column], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table(NEW_TABLE):
        return

    # Заявки на франшизу в старую схему не помещаются (нет email) — откат
    # их удаляет, идеи переезжают обратно.
    op.execute(sa.text(f"DELETE FROM {NEW_TABLE} WHERE topic <> 'idea'"))
    op.execute(sa.text(f"UPDATE {NEW_TABLE} SET email = '' WHERE email IS NULL"))

    for name in (
        "ix_feedback_messages_topic",
        "ix_feedback_messages_created_at",
        "ix_feedback_messages_email",
    ):
        if name in _index_names(bind, NEW_TABLE):
            op.drop_index(name, table_name=NEW_TABLE)

    with op.batch_alter_table(NEW_TABLE) as batch:
        batch.alter_column(
            "email",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch.alter_column(
            "message",
            new_column_name="idea",
            existing_type=sa.Text(),
            existing_nullable=False,
        )
        batch.drop_column("city")
        batch.drop_column("phone")
        batch.drop_column("source")
        batch.drop_column("topic")

    op.rename_table(NEW_TABLE, OLD_TABLE)
    op.create_index("ix_rental_ideas_email", OLD_TABLE, ["email"], unique=False)
    op.create_index(
        "ix_rental_ideas_created_at", OLD_TABLE, ["created_at"], unique=False
    )
