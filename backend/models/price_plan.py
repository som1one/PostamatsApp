from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin


class PricePlan(Base, TimestampMixin):
    __tablename__ = "price_plans"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("products.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    duration_type: Mapped[str] = mapped_column(String, nullable=False)
    duration_value: Mapped[int] = mapped_column(nullable=False)
    base_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String, default="RUB", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    
