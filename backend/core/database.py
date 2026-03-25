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

async def init_db():
    for module_name in (
        "backend.models.admin_user",
        "backend.models.auth_session",
        "backend.models.auth_verification_session",
        "backend.models.city",
        "backend.models.condition_report",
        "backend.models.condition_report_photo",
        "backend.models.inventory_movement",
        "backend.models.inventory_unit",
        "backend.models.locker_cell",
        "backend.models.locker_location",
        "backend.models.media_file",
        "backend.models.payment",
        "backend.models.payment_event",
        "backend.models.price_plan",
        "backend.models.product",
        "backend.models.product_category",
        "backend.models.product_image",
        "backend.models.rental",
        "backend.models.rental_event",
        "backend.models.reservation",
        "backend.models.user",
        "backend.models.verification_request",
    ):
        import_module(module_name)

async def close_db():
    await engine.dispose()