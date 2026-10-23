from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base, TimestampMixin


class WeekdayPriceMarkup(Base, TimestampMixin):
    """Наценка к цене суток аренды в конкретный день недели.

    Одна строка на день: ``weekday`` — как ``date.weekday()`` (0 — пн,
    6 — вс), ``percent`` — наценка в процентах, отрицательная — скидка.
    Нет строки — наценки в этот день нет. Действует только на товары с
    ``products.weekday_pricing_enabled`` (см. backend/utils/rental_pricing.py).
    """

    __tablename__ = "weekday_price_markups"

    weekday: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
