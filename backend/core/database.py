from datetime import datetime
from enum import Enum
from importlib import import_module

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.core.settings import settings

engine = create_async_engine(settings.ASYNC_DB_URL)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


async def get_db():
    async with SessionLocal() as db:
        yield db

def _resolve_postgres_enum_labels(
    enum_cls: type[Enum],
    existing: set[str],
) -> set[str]:
    names = {member.name for member in enum_cls}
    values = {
        str(member.value)
        for member in enum_cls
        if isinstance(member.value, str)
    }
    if existing & names:
        return names
    if existing & values:
        return values
    return names


async def _ensure_postgres_enum_values(
    conn,
    *,
    type_name: str,
    enum_cls: type[Enum],
) -> None:
    """Synchronize a Postgres enum type with the current Python enum members."""
    from sqlalchemy import text

    rows = await conn.execute(
        text(
            "SELECT enumlabel FROM pg_enum e "
            "JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = :type_name"
        ),
        {"type_name": type_name},
    )
    existing = {row[0] for row in rows.all()}
    expected = _resolve_postgres_enum_labels(enum_cls, existing)

    for label in expected - existing:
        safe = label.replace("'", "''")
        await conn.execute(
            text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{safe}'")
        )


async def _table_has_column(
    conn,
    *,
    table_name: str,
    column_name: str,
) -> bool:
    from sqlalchemy import inspect

    def _inspect(sync_conn):
        columns = inspect(sync_conn).get_columns(table_name)
        return any(column.get("name") == column_name for column in columns)

    return bool(await conn.run_sync(_inspect))


async def _ensure_inventory_last_check_column(conn) -> None:
    from sqlalchemy import text

    if await _table_has_column(
        conn,
        table_name="inventory_units",
        column_name="last_check_at",
    ):
        return

    dialect = conn.dialect.name
    if dialect == "postgresql":
        await conn.execute(
            text(
                "ALTER TABLE inventory_units "
                "ADD COLUMN IF NOT EXISTS last_check_at TIMESTAMP WITH TIME ZONE"
            )
        )
    elif dialect == "sqlite":
        await conn.execute(
            text(
                "ALTER TABLE inventory_units "
                "ADD COLUMN last_check_at DATETIME"
            )
        )


async def init_db():
    for module_name in (
        "backend.models.admin_account",
        "backend.models.admin_audit_event",
        "backend.models.admin_auth_session",
        "backend.models.admin_user",
        "backend.models.auth_session",
        "backend.models.auth_verification_session",
        "backend.models.city",
        "backend.models.condition_report",
        "backend.models.condition_report_photo",
        "backend.models.esi_event_log",
        "backend.models.featured_product_state",
        "backend.models.inventory_movement",
        "backend.models.inventory_unit",
        "backend.models.locker_cell",
        "backend.models.locker_location",
        "backend.models.media_file",
        "backend.models.payment",
        "backend.models.payment_event",
        "backend.models.price_plan",
        "backend.models.product",
        "backend.models.product_filter",
        "backend.models.product_category",
        "backend.models.product_image",
        "backend.models.rental",
        "backend.models.rental_event",
        "backend.models.rental_idea",
        "backend.models.return_request",
        "backend.models.reservation",
        "backend.models.support_conversation",
        "backend.models.support_conversation_read",
        "backend.models.support_message",
        "backend.models.telegram_admin_subscriber",
        "backend.models.user",
        "backend.models.verification_request",
    ):
        import_module(module_name)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await _ensure_inventory_last_check_column(conn)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("failed to sync inventory_units.last_check_at")
    if engine.dialect.name == "postgresql":
        async with engine.begin() as conn:
            try:
                from backend.models.enums import InventoryStatus, MediaFileKind

                await _ensure_postgres_enum_values(
                    conn,
                    type_name="media_file_kind",
                    enum_cls=MediaFileKind,
                )
                await _ensure_postgres_enum_values(
                    conn,
                    type_name="inventory_status",
                    enum_cls=InventoryStatus,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("failed to sync postgres enum values")

            try:
                from sqlalchemy import text
                await conn.execute(text("CREATE SEQUENCE IF NOT EXISTS support_message_seq"))
            except Exception:
                import logging
                logging.getLogger(__name__).exception("failed to create support_message_seq")

async def close_db():
    await engine.dispose()
