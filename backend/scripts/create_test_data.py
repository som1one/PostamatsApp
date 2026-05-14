"""
Создаёт тестовый аккаунт с тестовой бронью на несуществующий постамат в Москве.

Запуск:
    python -m backend.scripts.create_test_data
или из папки backend/:
    python scripts/create_test_data.py
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.database import SessionLocal, init_db
from backend.models.city import City
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    PaymentStatus,
    PaymentType,
    RentalEventSource,
    RentalStatus,
    ReservationStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.payment import Payment
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.reservation import Reservation
from backend.models.user import User
from sqlalchemy import select


TEST_PHONE = "+79991234567"
TEST_FIRST_NAME = "Тест"
TEST_LAST_NAME = "Тестов"


async def main() -> None:
    await init_db()

    async with SessionLocal() as db:
        now = datetime.now(timezone.utc)

        # ── 1. Город Москва ──────────────────────────────────────────────────
        city = (await db.scalars(select(City).where(City.slug == "moscow").limit(1))).first()
        if city is None:
            city = City(
                id=uuid4(),
                name="Москва",
                slug="moscow",
                timezone="Europe/Moscow",
                is_active=True,
                sort_order=1,
            )
            db.add(city)
            await db.flush()
            print(f"[+] Город создан: {city.name} ({city.id})")
        else:
            print(f"[=] Город уже есть: {city.name} ({city.id})")

        # ── 2. Пользователь ───────────────────────────────────────────────────
        user = (await db.scalars(select(User).where(User.phone == TEST_PHONE).limit(1))).first()
        if user is None:
            user = User(
                id=uuid4(),
                phone=TEST_PHONE,
                first_name=TEST_FIRST_NAME,
                last_name=TEST_LAST_NAME,
                preferred_city_id=city.id,
                verification_status=VerificationStatus.APPROVED,
            )
            db.add(user)
            await db.flush()
            print(f"[+] Пользователь создан: {user.phone} ({user.id})")
        else:
            print(f"[=] Пользователь уже есть: {user.phone} ({user.id})")

        # ── 3. Несуществующий постамат в Москве ───────────────────────────────
        locker = (
            await db.scalars(
                select(LockerLocation)
                .where(LockerLocation.external_locker_id == "test-moscow-fake-001")
                .limit(1)
            )
        ).first()
        if locker is None:
            locker = LockerLocation(
                id=uuid4(),
                city_id=city.id,
                name="Тестовый постамат (несуществующий)",
                address="Москва, ул. Несуществующая, д. 0",
                lat=55.751244,
                lon=37.618423,
                status=LockerStatus.ONLINE,
                external_provider="esi",
                external_locker_id="test-moscow-fake-001",
            )
            db.add(locker)
            await db.flush()
            print(f"[+] Постамат создан: {locker.name} ({locker.id})")
        else:
            print(f"[=] Постамат уже есть: {locker.name} ({locker.id})")

        # ── 4. Ячейка постамата ───────────────────────────────────────────────
        cell = (
            await db.scalars(
                select(LockerCell).where(LockerCell.locker_id == locker.id).limit(1)
            )
        ).first()
        if cell is None:
            cell = LockerCell(
                id=uuid4(),
                locker_id=locker.id,
                external_cell_id="test-cell-001",
                label="A1",
                size="medium",
                status=LockerCellStatus.RESERVED,
                supports_return=True,
            )
            db.add(cell)
            await db.flush()
            print(f"[+] Ячейка создана: {cell.label} ({cell.id})")
        else:
            print(f"[=] Ячейка уже есть: {cell.label} ({cell.id})")

        # ── 5. Категория товара ───────────────────────────────────────────────
        category = (
            await db.scalars(
                select(ProductCategory).where(ProductCategory.slug == "test-category").limit(1)
            )
        ).first()
        if category is None:
            category = ProductCategory(
                id=uuid4(),
                name="Тестовая категория",
                slug="test-category",
                is_active=True,
                sort_order=99,
            )
            db.add(category)
            await db.flush()
            print(f"[+] Категория создана: {category.name} ({category.id})")
        else:
            print(f"[=] Категория уже есть: {category.name} ({category.id})")

        # ── 6. Товар ──────────────────────────────────────────────────────────
        product = (
            await db.scalars(
                select(Product).where(Product.slug == "test-product-001").limit(1)
            )
        ).first()
        if product is None:
            product = Product(
                id=uuid4(),
                category_id=category.id,
                name="Тестовый товар",
                slug="test-product-001",
                short_description="Тестовый товар для разработки",
                brand="TestBrand",
                is_active=True,
            )
            db.add(product)
            await db.flush()
            print(f"[+] Товар создан: {product.name} ({product.id})")
        else:
            print(f"[=] Товар уже есть: {product.name} ({product.id})")

        # ── 7. Прайс-план ─────────────────────────────────────────────────────
        price_plan = (
            await db.scalars(
                select(PricePlan)
                .where(PricePlan.product_id == product.id, PricePlan.duration_type == "day")
                .limit(1)
            )
        ).first()
        if price_plan is None:
            price_plan = PricePlan(
                id=uuid4(),
                product_id=product.id,
                name="1 день",
                duration_type="day",
                duration_value=1,
                base_amount=Decimal("500.00"),
                currency="RUB",
                is_active=True,
                sort_order=0,
            )
            db.add(price_plan)
            await db.flush()
            print(f"[+] Прайс-план создан: {price_plan.name} ({price_plan.id})")
        else:
            print(f"[=] Прайс-план уже есть: {price_plan.name} ({price_plan.id})")

        # ── 8. Единица инвентаря ──────────────────────────────────────────────
        unit = (
            await db.scalars(
                select(InventoryUnit).where(InventoryUnit.locker_cell_id == cell.id).limit(1)
            )
        ).first()
        if unit is None:
            unit = InventoryUnit(
                id=uuid4(),
                product_id=product.id,
                locker_cell_id=cell.id,
                serial_number="TEST-SN-001",
                status=InventoryStatus.RESERVED,
            )
            db.add(unit)
            await db.flush()
            print(f"[+] Единица инвентаря создана: {unit.serial_number} ({unit.id})")
        else:
            print(f"[=] Единица инвентаря уже есть: ({unit.id})")

        # ── 9. Резервация (подтверждённая) ────────────────────────────────────
        reservation = (
            await db.scalars(
                select(Reservation)
                .where(
                    Reservation.user_id == user.id,
                    Reservation.inventory_unit_id == unit.id,
                    Reservation.status == ReservationStatus.CONFIRMED,
                )
                .limit(1)
            )
        ).first()
        if reservation is None:
            reservation = Reservation(
                id=uuid4(),
                user_id=user.id,
                product_id=product.id,
                inventory_unit_id=unit.id,
                locker_id=locker.id,
                price_plan_id=price_plan.id,
                status=ReservationStatus.CONFIRMED,
                duration_type="day",
                duration_value=1,
                quoted_amount=Decimal("500.00"),
                preauth_amount=Decimal("1000.00"),
                expires_at=now + timedelta(hours=2),
                confirmed_at=now,
            )
            db.add(reservation)
            await db.flush()
            print(f"[+] Резервация создана: ({reservation.id})")
        else:
            print(f"[=] Резервация уже есть: ({reservation.id})")

        # ── 10. Платёж (авторизован) ──────────────────────────────────────────
        payment = (
            await db.scalars(
                select(Payment)
                .where(Payment.reservation_id == reservation.id)
                .limit(1)
            )
        ).first()
        if payment is None:
            payment = Payment(
                id=uuid4(),
                user_id=user.id,
                reservation_id=reservation.id,
                provider="yookassa",
                provider_payment_id=f"test-payment-{uuid4().hex[:8]}",
                type=PaymentType.PREAUTH,
                status=PaymentStatus.AUTHORIZED,
                amount=Decimal("1000.00"),
                currency="RUB",
                processed_at=now,
            )
            db.add(payment)
            await db.flush()
            print(f"[+] Платёж создан: ({payment.id})")
        else:
            print(f"[=] Платёж уже есть: ({payment.id})")

        # ── 11. Аренда (PICKUP_READY) ─────────────────────────────────────────
        rental = (
            await db.scalars(
                select(Rental).where(Rental.reservation_id == reservation.id).limit(1)
            )
        ).first()
        if rental is None:
            rental = Rental(
                id=uuid4(),
                user_id=user.id,
                reservation_id=reservation.id,
                inventory_unit_id=unit.id,
                pickup_locker_id=locker.id,
                pickup_pin="4242",
                status=RentalStatus.PICKUP_READY,
                pickup_expires_at=now + timedelta(minutes=30),
                planned_end_at=now + timedelta(days=1),
            )
            db.add(rental)
            await db.flush()

            db.add(
                RentalEvent(
                    rental_id=rental.id,
                    event_type="reservation_confirmed",
                    from_status=None,
                    to_status=RentalStatus.PICKUP_READY,
                    source=RentalEventSource.SYSTEM,
                    payload_json={"note": "test seed"},
                )
            )
            await db.flush()
            print(f"[+] Аренда создана: ({rental.id}), PIN: {rental.pickup_pin}")
        else:
            print(f"[=] Аренда уже есть: ({rental.id}), PIN: {rental.pickup_pin}")

        await db.commit()

    print()
    print("=" * 60)
    print("Тестовые данные готовы:")
    print(f"  Телефон:  {TEST_PHONE}")
    print(f"  Имя:      {TEST_FIRST_NAME} {TEST_LAST_NAME}")
    print(f"  Постамат: Москва, ул. Несуществующая, д. 0")
    print(f"  PIN:      4242")
    print(f"  Статус:   PICKUP_READY (истекает через 30 мин)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
