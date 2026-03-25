from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    category_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("product_categories.id"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    short_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    specs_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    rules_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    kit_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_file_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("media_files.id"),
        index=True,
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
