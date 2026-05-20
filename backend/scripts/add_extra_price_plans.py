"""
Заполняет всем активным товарам тарифы 1, 2, 3, 4, 5, 6, 7 и 14 дней,
рассчитанные от существующего тарифа "1 день".

Множители (итоговая стоимость относительно 1 дня) подобраны под скидочную
сетку старого магазина naprokatberu.ru: чем дольше аренда, тем меньше
средняя цена за сутки. Конкретно: 1 день = x1, 7 дней = x4.27 (≈610 ₽
за сутки против 1626 ₽), 14 дней = x7.14 (≈830 ₽ за сутки). Промежуточные
значения для 2/4/5/6 дней — линейная интерполяция.

Цены округляются до 10 рублей.

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


# (имя, duration_type, duration_value, множитель относительно тарифа "1 день", sort_order)
EXTRA_PLANS: list[tuple[str, str, int, Decimal, int]] = [
    ("2 дня", "day", 2, Decimal("1.85"), 1),
    ("3 дня", "day", 3, Decimal("2.55"), 2),
    ("4 дня", "day", 4, Decimal("2.90"), 3),
    ("5 дней", "day", 5, Decimal("3.40"), 4),
    ("6 дней", "day", 6, Decimal("3.84"), 5),
    ("7 дней", "day", 7, Decimal("4.27"), 6),
    ("14 дней", "day", 14, Decimal("7.14"), 7),
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
