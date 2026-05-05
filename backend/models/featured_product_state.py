from datetime import date
from uuid import UUID

from sqlalchemy import Date, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin


class FeaturedProductState(Base, TimestampMixin):
    __tablename__ = "featured_product_state"

    spotlight_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )
    active_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
