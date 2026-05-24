"""
Заполняет всем активным товарам тарифы 1, 2, 3, 4, 5, 6, 7 и 14 дней,
рассчитанные от существующего тарифа "1 день" (его ``base_amount`` —
прайс-лист за сутки без скидки).

Прогрессирующая скидка от срока аренды:
    1 день — 5%, 2 дня — 10%, 3 дня — 15%, далее +3% за каждый
    дополнительный день. То есть 4 — 18%, 5 — 21%, 6 — 24%, …,
    14 — 48%. Скидка ограничена 90% сверху.

Итоговая стоимость аренды на ``days`` суток равна
``days * base_amount * (1 - discount(days))``. Цены округляются до 10 рублей.

Эта же формула продублирована на фронте в
``web/src/shared/rentalPricing.ts``; правьте в обоих местах.

Запуск (внутри backend-контейнера):
    python -m backend.scripts.add_extra_price_plans
    # или с пересозданием:
    python -m backend.scripts.add_extra_price_plans --force
"""

import argparse
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import SessionLocal
from backend.models.price_plan import PricePlan
from backend.models.product import Product


def _progressive_discount(days: int) -> Decimal:
    """Возвращает скидку (доля 0..1) для тарифа на ``days`` суток.

    1 — 5%, 2 — 10%, 3 — 15%, далее +3% за каждые сутки. Скидка ограничена
    сверху 90%. См. также ``web/src/shared/rentalPricing.ts``.
    """

    if days <= 0:
        return Decimal("0")
    if days == 1:
        percent = 5
    elif days == 2:
        percent = 10
    elif days == 3:
        percent = 15
    else:
        # 4 дн -> 18%, 5 -> 21%, 6 -> 24%, ... +3% за каждый день после 3-го
        percent = 15 + (days - 3) * 3
    percent = max(0, min(percent, 90))
    return Decimal(percent) / Decimal(100)


def _multiplier_for(days: int) -> Decimal:
    return (Decimal(days) * (Decimal("1") - _progressive_discount(days))).quantize(
        Decimal("0.0001")
    )


def _plan_name(days: int) -> str:
    last_two = days % 100
    last = days % 10
    if 11 <= last_two <= 14:
        word = "дней"
    elif last == 1:
        word = "день"
    elif 2 <= last <= 4:
        word = "дня"
    else:
        word = "дней"
    return f"{days} {word}"


# (имя, duration_type, duration_value, множитель относительно базовой цены
#  за сутки, sort_order). 1-дневный тариф остаётся неизменным и трактуется
#  как «список без скидки» — все остальные тарифы пересчитываются от него.
EXTRA_PLAN_DAYS: list[int] = [2, 3, 4, 5, 6, 7, 14]
EXTRA_PLANS: list[tuple[str, str, int, Decimal, int]] = [
    (_plan_name(days), "day", days, _multiplier_for(days), index + 1)
    for index, days in enumerate(EXTRA_PLAN_DAYS)
]


def _round_to_10_rub(amount: Decimal) -> Decimal:
    """Округляет рубли до 10 (например 1593 → 1590)."""
    quantum = Decimal("10")
    rounded = (amount / quantum).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * quantum
    return rounded.quantize(Decimal("0.01"))


async def _process_product(db: AsyncSession, product: Product, force: bool) -> None:
    base_plan = (
        await db.scalars(
            select(PricePlan)
            .where(
                PricePlan.product_id == product.id,
                PricePlan.duration_type == "day",
                PricePlan.duration_value == 1,
                PricePlan.is_active.is_(True),
            )
            .limit(1)
        )
    ).first()

    if base_plan is None:
        print(f"[skip] {product.name}: нет тарифа на 1 день, пропускаю")
        return

    base_plan.sort_order = 0

    for name, duration_type, duration_value, multiplier, sort_order in EXTRA_PLANS:
        existing = (
            await db.scalars(
                select(PricePlan)
                .where(
                    PricePlan.product_id == product.id,
                    PricePlan.duration_type == duration_type,
                    PricePlan.duration_value == duration_value,
                )
                .limit(1)
            )
        ).first()

        amount = _round_to_10_rub(Decimal(base_plan.base_amount) * multiplier)

        if existing is None:
            plan = PricePlan(
                id=uuid4(),
                product_id=product.id,
                name=name,
                duration_type=duration_type,
                duration_value=duration_value,
                base_amount=amount,
                currency=base_plan.currency,
                is_active=True,
                sort_order=sort_order,
            )
            db.add(plan)
            print(f"[+] {product.name}: создан тариф {name} = {amount} {base_plan.currency}")
        elif force:
            existing.name = name
            existing.base_amount = amount
            existing.is_active = True
            existing.sort_order = sort_order
            print(f"[~] {product.name}: обновлён тариф {name} = {amount} {base_plan.currency}")
        else:
            print(f"[=] {product.name}: тариф {name} уже есть ({existing.base_amount}), пропускаю")


async def main(force: bool) -> None:
    async with SessionLocal() as db:
        products = (
            await db.scalars(select(Product).where(Product.is_active.is_(True)))
        ).all()
        print(f"Активных товаров: {len(products)}")

        for product in products:
            await _process_product(db, product, force)

        await db.commit()
        print("Готово.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать существующие тарифы 3/7/14 дней",
    )
    args = parser.parse_args()
    asyncio.run(main(force=args.force))
