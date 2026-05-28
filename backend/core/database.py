from datetime import datetime
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

async def _ensure_media_file_kind_values(conn) -> None:
    """Add any missing values from Python MediaFileKind enum into the
    existing Postgres enum `media_file_kind`.

    SQLAlchemy `metadata.create_all` does not synchronize values of
    existing enums, so adding a new member to the Python enum has to
    be backed by either a migration or a runtime sync. We do the
    runtime sync here so that the app works even if the alembic
    migration has not been applied yet.
    """
    from sqlalchemy import text
    from backend.models.enums import MediaFileKind

    rows = await conn.execute(
        text(
            "SELECT enumlabel FROM pg_enum e "
            "JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = 'media_file_kind'"
        )
    )
    existing = {row[0] for row in rows.all()}
    # SQLAlchemy by default sends member names, not values, for enums
    # created via metadata.create_all (no values_callable). So we add
    # both the name and the value to be safe in either schema.
    expected: set[str] = set()
    for member in MediaFileKind:
        expected.add(member.name)
        expected.add(member.value)

    for label in expected - existing:
        # Quote single quotes inside the label defensively, even though
        # all enum labels are simple identifiers.
        safe = label.replace("'", "''")
        await conn.execute(
            text(f"ALTER TYPE media_file_kind ADD VALUE IF NOT EXISTS '{safe}'")
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
        "backend.models.telegram_admin_subscriber",
        "backend.models.user",
        "backend.models.verification_request",
    ):
        import_module(module_name)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if engine.dialect.name == "postgresql":
        async with engine.begin() as conn:
            try:
                await _ensure_media_file_kind_values(conn)
            except Exception:
                # Не валим запуск, если что-то пошло не так — просто
                # не синхронизируем enum. Логи покажут причину.
                import logging

                logging.getLogger(__name__).exception(
                    "failed to sync media_file_kind enum values"
                )

async def close_db():
    await engine.dispose()
