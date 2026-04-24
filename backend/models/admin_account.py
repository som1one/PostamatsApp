from uuid import UUID, uuid4

from sqlalchemy import Enum as SQLAlchemyEnum, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from backend.models.enums import AdminRole


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
