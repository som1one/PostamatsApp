from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLAlchemyEnum,
    String,
    Uuid,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.models.admin_account_city import admin_account_cities
from backend.models.city import City
from backend.models.enums import AdminRole


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AdminAccount(Base):
    __tablename__ = "admin_accounts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    login: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    role: Mapped[AdminRole] = mapped_column(
        SQLAlchemyEnum(
            AdminRole,
            name="admin_account_role",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        default=AdminRole.SUPER_ADMIN,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    # Города франшизы: один или несколько. У super_admin/operator список
    # пустой — они видят всю сеть. Грузим сразу (``selectin``): скоуп нужен
    # почти в каждом админском запросе, а ленивая подгрузка в async-сессии
    # просто упала бы.
    cities: Mapped[list[City]] = relationship(
        City,
        secondary=admin_account_cities,
        lazy="selectin",
        order_by=City.name,
    )
    # Выключенный аккаунт не может войти, а его активные сессии отзываются.
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Nullable, чтобы миграция на живой таблице не требовала бэкфилла.
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=True,
    )
