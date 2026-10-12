"""Цена аренды на срок, под который у товара нет готового тарифа.

Клиент выбирает в календаре любые даты, а тарифы в ``price_plans`` заведены
только на часть сроков (у большинства товаров — один «1 день»). Раньше
витрина подставляла ближайший тариф снизу и оформляла аренду на его срок:
человек выбирал 9 суток, а платил и получал вещь на одни.

Срок без своего тарифа считается от тарифа «1 день» по шкале, которую сайт
показывает под календарём: 2 суток — −5%, 3 — −10%, далее −1% за каждые
следующие сутки, но не больше 25% за весь срок. Готовый тариф на тот же
срок всегда главнее шкалы — тарифы на 2/3/7 дней в
``deploy/catalog-sync.bundle.json`` посчитаны этой же шкалой, при смене
шкалы или суточной цены их надо пересчитать.

Формула продублирована на фронте в ``web/src/shared/rentalPricing.ts`` и
``mobile/src/shared/rentalPricing.ts``; правьте во всех местах.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.price_plan import PricePlan
from backend.models.product_filter import ProductFilter
from backend.utils.lockers_utils import price_plan_to_minor_units
from backend.utils.product_filters import find_effective_filter_price_plan
from backend.utils.products_utils import find_price_plan

MAX_DISCOUNT_PERCENT = 25

# Календарь на витрине даёт выбрать даты в пределах 30 дней. Дальше шкалу
# не тянем, чтобы ручной запрос не оформил аренду на год.
MAX_PROGRESSIVE_DAYS = 30

# Сумма округляется до 10 ₽ (1000 минорных единиц), как в готовых тарифах.
_ROUND_TO_MINOR = 1000


def progressive_discount_percent(days: int) -> int:
    """Скидка в процентах для аренды на ``days`` суток."""
    if days <= 1:
        return 0
    if days == 2:
        return 5
    return min(10 + (days - 3), MAX_DISCOUNT_PERCENT)


def progressive_total_minor(base_per_day_minor: int, days: int) -> int:
    """Стоимость ``days`` суток в минорных единицах от цены одних суток."""
    if base_per_day_minor <= 0 or days <= 0:
        return 0
    # Считаем в целых: float на границе округления расходится с фронтом.
    scaled = base_per_day_minor * days * (100 - progressive_discount_percent(days))
    step = _ROUND_TO_MINOR * 100
    return (scaled + step // 2) // step * _ROUND_TO_MINOR


@dataclass(frozen=True)
class RentalPrice:
    # Строка тарифа для ``reservations.price_plan_id``. У срока по шкале это
    # тариф «1 день», от которого посчитана сумма. None — цена задана только
    # в product_filter, а строки тарифа под неё нет.
    plan: PricePlan | None
    amount_minor: int
    currency: str


async def _find_exact_price(
    db: AsyncSession,
    product_id: UUID,
    product_filter: ProductFilter | None,
    duration_type: str,
    duration_value: int,
) -> RentalPrice | None:
    filter_plan = find_effective_filter_price_plan(
        product_filter, duration_type, duration_value
    )
    plan = await find_price_plan(db, product_id, duration_type, duration_value)
    if filter_plan is not None:
        return RentalPrice(
            plan=plan,
            amount_minor=int(filter_plan["baseAmount"]),
            currency=str(filter_plan["currency"]),
        )
    if plan is None:
        return None
    return RentalPrice(
        plan=plan,
        amount_minor=price_plan_to_minor_units(plan.base_amount, plan.currency),
        currency=plan.currency,
    )


async def resolve_rental_price(
    db: AsyncSession,
    product_id: UUID,
    product_filter: ProductFilter | None,
    duration_type: str,
    duration_value: int,
) -> RentalPrice | None:
    """Цена аренды товара на выбранный срок или None, если посчитать не от чего."""
    exact = await _find_exact_price(
        db, product_id, product_filter, duration_type, duration_value
    )
    if exact is not None:
        return exact

    if duration_type.strip().lower() != "day":
        return None
    if not 1 < duration_value <= MAX_PROGRESSIVE_DAYS:
        return None

    base = await _find_exact_price(db, product_id, product_filter, "day", 1)
    if base is None or base.amount_minor <= 0:
        return None
    return RentalPrice(
        plan=base.plan,
        amount_minor=progressive_total_minor(base.amount_minor, duration_value),
        currency=base.currency,
    )
