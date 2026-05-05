from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin


class ProductFilter(Base, TimestampMixin):
    __tablename__ = "product_filters"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id"),
        unique=True,
        index=True,
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    short_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    kit_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    gallery_urls_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    price_plans_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
