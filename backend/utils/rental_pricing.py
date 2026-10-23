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

Поверх цены за срок может действовать наценка по дням недели (владелец
поднимает цену на выходные): у товара с галочкой
``products.weekday_pricing_enabled`` каждые сутки аренды дорожают на процент
своего дня из ``weekday_price_markups``. Сутки считаются от даты выдачи:
аренда с пятницы на 2 суток — это пятница и суббота.

Формула продублирована на фронте в ``web/src/shared/rentalPricing.ts`` и
``mobile/src/shared/rentalPricing.ts``; правьте во всех местах.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_filter import ProductFilter
from backend.models.weekday_price_markup import WeekdayPriceMarkup
from backend.utils.lockers_utils import price_plan_to_minor_units
from backend.utils.product_filters import find_effective_filter_price_plan
from backend.utils.products_utils import find_price_plan
from backend.utils.reservation_utils import LOCAL_DAY_TZ, ensure_utc

MAX_DISCOUNT_PERCENT = 25

# Календарь на витрине даёт выбрать даты в пределах 30 дней. Дальше шкалу
# не тянем, чтобы ручной запрос не оформил аренду на год.
MAX_PROGRESSIVE_DAYS = 30

# Сумма округляется до 10 ₽ (1000 минорных единиц), как в готовых тарифах.
_ROUND_TO_MINOR = 1000

# Пределы наценки дня недели в админке. Снизу — чтобы опечатка «-100» не
# сделала выходные бесплатными.
WEEKDAY_MARKUP_MIN_PERCENT = -50
WEEKDAY_MARKUP_MAX_PERCENT = 200


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


def weekday_markup_total_minor(
    amount_minor: int,
    start_date: date,
    days: int,
    markups: tuple[int, ...],
) -> int:
    """Сумма за ``days`` суток с ``start_date`` с наценкой дней недели.

    ``markups`` — проценты с понедельника по воскресенье. Сумма за срок
    умножается на среднюю по суткам наценку, поэтому скидка за срок
    сохраняется: 3 суток с пятницы при +20% на пт, сб и вс стоят ровно на
    20% дороже, неделя с понедельника — на 60/7 ≈ 8,6%.
    """
    if amount_minor <= 0 or days <= 0:
        return amount_minor
    markup_sum = sum(
        markups[(start_date.weekday() + offset) % 7] for offset in range(days)
    )
    if markup_sum == 0:
        # Цену без наценки не переокругляем: тариф из product_filter может
        # быть не кратен 10 ₽.
        return amount_minor
    scaled = amount_minor * (100 * days + markup_sum)
    step = _ROUND_TO_MINOR * 100 * days
    return (scaled + step // 2) // step * _ROUND_TO_MINOR


def rental_start_day(start_at: datetime | None, now: datetime | None = None) -> date:
    """Календарный день первых суток аренды — от него считаются дни недели.

    ``startAt`` с сайта — полночь выбранной даты в поясе браузера, поэтому
    берётся ближайшая к нему полночь по Москве: у клиента из Екатеринбурга
    это 22:00 предыдущего дня по Москве, а день он выбрал свой. Продление
    с 15:00 пятницы так же считается субботой — большая часть суток на неё.
    Без ``startAt`` аренда начинается сейчас — это сегодняшняя дата.
    """
    if start_at is None:
        moment = now or datetime.now(timezone.utc)
        return ensure_utc(moment).astimezone(LOCAL_DAY_TZ).date()
    return (ensure_utc(start_at).astimezone(LOCAL_DAY_TZ) + timedelta(hours=12)).date()


async def load_weekday_markups(db: AsyncSession) -> tuple[int, ...]:
    """Наценки в процентах с понедельника по воскресенье."""
    markups = [0] * 7
    for row in (await db.scalars(select(WeekdayPriceMarkup))).all():
        if 0 <= row.weekday <= 6:
            markups[row.weekday] = int(row.percent)
    return tuple(markups)


async def load_product_weekday_markups(
    db: AsyncSession, product_id: UUID
) -> tuple[int, ...] | None:
    """Наценки для товара или None, если его цена от дня недели не зависит."""
    product = await db.get(Product, product_id)
    if product is None or not product.weekday_pricing_enabled:
        return None
    markups = await load_weekday_markups(db)
    return markups if any(markups) else None


def term_days(duration_type: str, duration_value: int) -> int:
    """Сколько суток срока получают наценку: часовой тариф — одни, первые."""
    if duration_type.strip().lower() == "day":
        return duration_value
    return 1


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
    *,
    start_date: date | None = None,
) -> RentalPrice | None:
    """Цена аренды товара на выбранный срок или None, если посчитать не от чего.

    ``start_date`` — день выдачи (см. ``rental_start_day``), по умолчанию
    сегодня; нужен товарам с ценой по дням недели.
    """
    price = await _resolve_term_price(
        db, product_id, product_filter, duration_type, duration_value
    )
    if price is None:
        return None
    markups = await load_product_weekday_markups(db, product_id)
    if markups is None:
        return price
    return replace(
        price,
        amount_minor=weekday_markup_total_minor(
            price.amount_minor,
            start_date or rental_start_day(None),
            term_days(duration_type, duration_value),
            markups,
        ),
    )


async def _resolve_term_price(
    db: AsyncSession,
    product_id: UUID,
    product_filter: ProductFilter | None,
    duration_type: str,
    duration_value: int,
) -> RentalPrice | None:
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
