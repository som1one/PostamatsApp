"""Тесты бонусной программы.

Правила, которые здесь закреплены:
  - 7% начисляются в момент завершения аренды и считаются от суммы,
    оплаченной ДЕНЬГАМИ (бонусы не порождают бонусы);
  - списать бонусами можно не больше 90% заказа и не больше баланса;
  - при отмене или экспирации заказа списанные бонусы возвращаются, причём
    ровно один раз, сколько бы точек отмены ни сработало.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

# DSN и стабы перекрываем ДО импорта приложения (как в test_full_flow_e2e).
TEST_DB_PATH = os.path.abspath(f"./backend/tests/test_bonus_{uuid4().hex}.sqlite")
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_URL"] = TEST_DB_URL
os.environ["ASYNC_DB_URL"] = TEST_DB_URL
os.environ["YOOKASSA_DEV_STUB"] = "true"
os.environ["ESI_DEV_STUB"] = "true"
os.environ["UPLOAD_DEV_STUB"] = "true"

from sqlalchemy import select  # noqa: E402

from backend.main import app  # noqa: E402,F401  (регистрирует все модели в metadata)
from backend.core.database import Base, SessionLocal, engine  # noqa: E402
from backend.models.bonus_transaction import BonusTransaction  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    BonusTransactionType,
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    PaymentStatus,
    PaymentType,
    RentalStatus,
    ReservationStatus,
    VerificationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.payment import Payment  # noqa: E402
from backend.models.price_plan import PricePlan  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.product_category import ProductCategory  # noqa: E402
from backend.models.rental import Rental  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.bonus_ledger import (  # noqa: E402
    BonusError,
    accrue_rental_bonus,
    admin_adjust,
    apply_bonus_spend,
    bonus_spent_for_reservation,
    get_balance,
    max_spendable,
    release_bonus_spend,
)
from backend.utils.reservation_expiry import expire_stale_reservations  # noqa: E402


class BonusProgramTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        self.city_id = uuid4()
        self.category_id = uuid4()
        self.product_id = uuid4()
        self.plan_id = uuid4()
        self.user_id = uuid4()

        async with SessionLocal() as db:
            db.add_all(
                [
                    City(
                        id=self.city_id,
                        name="Test City",
                        slug="test-city",
                        timezone="Europe/Moscow",
                        is_active=True,
                        sort_order=0,
                    ),
                    ProductCategory(
                        id=self.category_id,
                        name="Cat",
                        slug="cat",
                        is_active=True,
                        sort_order=0,
                    ),
                    Product(
                        id=self.product_id,
                        category_id=self.category_id,
                        name="Karaoke",
                        slug="karaoke",
                        is_active=True,
                    ),
                    PricePlan(
                        id=self.plan_id,
                        product_id=self.product_id,
                        name="1 day",
                        duration_type="day",
                        duration_value=1,
                        base_amount=Decimal("1000.00"),
                        currency="RUB",
                        is_active=True,
                    ),
                    User(
                        id=self.user_id,
                        phone="+79991112233",
                        verification_status=VerificationStatus.APPROVED,
                    ),
                ]
            )
            await db.commit()

    async def asyncTearDown(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        try:
            await engine.dispose()
            if os.path.exists(TEST_DB_PATH):
                os.remove(TEST_DB_PATH)
        except (PermissionError, OSError):
            pass

    # ── фикстуры ────────────────────────────────────────────────────────

    async def _seed_locker_unit(self):
        async with SessionLocal() as db:
            locker = LockerLocation(
                id=uuid4(),
                city_id=self.city_id,
                name="Locker",
                address="ул. Тестовая, 1",
                status=LockerStatus.ONLINE,
                external_provider="esi",
                external_locker_id=f"LOCKER-{uuid4().hex[:6]}",
            )
            cell = LockerCell(
                id=uuid4(),
                locker_id=locker.id,
                label="A1",
                external_cell_id="A1",
                status=LockerCellStatus.OCCUPIED,
                supports_return=True,
            )
            unit = InventoryUnit(
                id=uuid4(),
                product_id=self.product_id,
                locker_cell_id=cell.id,
                status=InventoryStatus.RESERVED,
                serial_number=f"SN-{uuid4().hex[:6]}",
            )
            db.add_all([locker, cell, unit])
            await db.commit()
            return locker.id, unit.id

    async def _seed_reservation(
        self,
        *,
        status: ReservationStatus = ReservationStatus.AWAITING_PAYMENT,
        quoted: str = "1000.00",
        expires_in: timedelta = timedelta(hours=2),
    ) -> Reservation:
        locker_id, unit_id = await self._seed_locker_unit()
        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            reservation = Reservation(
                id=uuid4(),
                user_id=self.user_id,
                product_id=self.product_id,
                inventory_unit_id=unit_id,
                locker_id=locker_id,
                price_plan_id=self.plan_id,
                status=status,
                duration_type="day",
                duration_value=1,
                quoted_amount=Decimal(quoted),
                preauth_amount=Decimal(quoted),
                expires_at=now + expires_in,
            )
            db.add(reservation)
            await db.commit()
            return reservation

    async def _seed_rental(
        self,
        *,
        reservation: Reservation,
        paid_amount: str | None,
    ) -> Rental:
        """Аренда по брони. `paid_amount` — сумма платежа, None — платежа нет."""
        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            rental = Rental(
                id=uuid4(),
                user_id=self.user_id,
                reservation_id=reservation.id,
                inventory_unit_id=reservation.inventory_unit_id,
                pickup_locker_id=reservation.locker_id,
                status=RentalStatus.ACTIVE,
                starts_at=now,
                planned_end_at=now + timedelta(days=1),
            )
            db.add(rental)
            if paid_amount is not None:
                db.add(
                    Payment(
                        id=uuid4(),
                        user_id=self.user_id,
                        reservation_id=reservation.id,
                        provider="yookassa",
                        provider_payment_id=f"yk-{uuid4().hex[:8]}",
                        type=PaymentType.PREAUTH,
                        status=PaymentStatus.CAPTURED,
                        amount=Decimal(paid_amount),
                        currency="RUB",
                    )
                )
            await db.commit()
            return rental

    async def _credit(self, amount: str) -> None:
        """Кладёт бонусы на счёт клиента через ручное начисление."""
        async with SessionLocal() as db:
            await admin_adjust(
                db,
                user_id=self.user_id,
                amount=Decimal(amount),
                direction="accrue",
                admin_account_id=None,
                comment="тестовое начисление",
            )
            await db.commit()

    async def _balance(self) -> Decimal:
        async with SessionLocal() as db:
            return await get_balance(db, self.user_id)

    # ── начисление ──────────────────────────────────────────────────────

    async def test_accrual_is_seven_percent_of_cash_paid(self):
        reservation = await self._seed_reservation()
        rental = await self._seed_rental(reservation=reservation, paid_amount="1000.00")

        async with SessionLocal() as db:
            rental = await db.get(Rental, rental.id)
            accrued = await accrue_rental_bonus(db, rental=rental)
            await db.commit()

        self.assertEqual(accrued, Decimal("70"))
        self.assertEqual(await self._balance(), Decimal("70.00"))

    async def test_accrual_is_idempotent(self):
        reservation = await self._seed_reservation()
        rental = await self._seed_rental(reservation=reservation, paid_amount="1000.00")

        for _ in range(3):
            async with SessionLocal() as db:
                fresh = await db.get(Rental, rental.id)
                await accrue_rental_bonus(db, rental=fresh)
                await db.commit()

        self.assertEqual(await self._balance(), Decimal("70.00"))
        async with SessionLocal() as db:
            rows = (
                await db.scalars(
                    select(BonusTransaction).where(
                        BonusTransaction.type == BonusTransactionType.ORDER_ACCRUAL
                    )
                )
            ).all()
        self.assertEqual(len(rows), 1)

    async def test_accrual_rounds_down_to_whole_rubles(self):
        """7% от 100 ₽ = 7 ₽; от 110 ₽ = 7.70 → 7 бонусов, копеек в бонусах нет."""
        reservation = await self._seed_reservation(quoted="110.00")
        rental = await self._seed_rental(reservation=reservation, paid_amount="110.00")

        async with SessionLocal() as db:
            fresh = await db.get(Rental, rental.id)
            accrued = await accrue_rental_bonus(db, rental=fresh)
            await db.commit()

        self.assertEqual(accrued, Decimal("7"))

    async def test_accrual_falls_back_to_reservation_when_no_payment(self):
        """Dev-stub: бронь подтверждена без платежа — начисляем от суммы брони."""
        reservation = await self._seed_reservation()
        rental = await self._seed_rental(reservation=reservation, paid_amount=None)

        async with SessionLocal() as db:
            fresh = await db.get(Rental, rental.id)
            accrued = await accrue_rental_bonus(db, rental=fresh)
            await db.commit()

        self.assertEqual(accrued, Decimal("70"))

    # ── списание ────────────────────────────────────────────────────────

    async def test_spend_is_capped_at_ninety_percent_of_order(self):
        await self._credit("5000")
        reservation = await self._seed_reservation(quoted="1000.00")

        async with SessionLocal() as db:
            limit = await max_spendable(
                db, user_id=self.user_id, order_amount=Decimal("1000.00")
            )
        self.assertEqual(limit, Decimal("900"))

        async with SessionLocal() as db:
            user = await db.get(User, self.user_id)
            fresh = await db.get(Reservation, reservation.id)
            with self.assertRaises(BonusError) as ctx:
                await apply_bonus_spend(
                    db, user=user, reservation=fresh, amount=Decimal("901")
                )
            self.assertEqual(ctx.exception.code, "BONUS_AMOUNT_INVALID")

    async def test_spend_is_capped_at_balance(self):
        await self._credit("100")
        reservation = await self._seed_reservation(quoted="1000.00")

        async with SessionLocal() as db:
            limit = await max_spendable(
                db, user_id=self.user_id, order_amount=Decimal("1000.00")
            )
        self.assertEqual(limit, Decimal("100"))

        async with SessionLocal() as db:
            user = await db.get(User, self.user_id)
            fresh = await db.get(Reservation, reservation.id)
            with self.assertRaises(BonusError):
                await apply_bonus_spend(
                    db, user=user, reservation=fresh, amount=Decimal("101")
                )

    async def test_spend_reduces_card_amount_but_not_order_price(self):
        await self._credit("400")
        reservation = await self._seed_reservation(quoted="1000.00")

        async with SessionLocal() as db:
            user = await db.get(User, self.user_id)
            fresh = await db.get(Reservation, reservation.id)
            applied = await apply_bonus_spend(
                db, user=user, reservation=fresh, amount=Decimal("400")
            )
            await db.commit()

        self.assertEqual(applied, Decimal("400"))
        self.assertEqual(await self._balance(), Decimal("0.00"))

        async with SessionLocal() as db:
            fresh = await db.get(Reservation, reservation.id)
            self.assertEqual(fresh.quoted_amount, Decimal("1000.00"))
            self.assertEqual(fresh.preauth_amount, Decimal("600.00"))

    async def test_repeated_spend_does_not_double_charge_balance(self):
        """Повторный клик «Оплатить» не должен списать бонусы дважды."""
        await self._credit("400")
        reservation = await self._seed_reservation(quoted="1000.00")

        for _ in range(3):
            async with SessionLocal() as db:
                user = await db.get(User, self.user_id)
                fresh = await db.get(Reservation, reservation.id)
                await apply_bonus_spend(
                    db, user=user, reservation=fresh, amount=Decimal("400")
                )
                await db.commit()

        self.assertEqual(await self._balance(), Decimal("0.00"))
        async with SessionLocal() as db:
            fresh = await db.get(Reservation, reservation.id)
            self.assertEqual(fresh.preauth_amount, Decimal("600.00"))
            self.assertEqual(
                await bonus_spent_for_reservation(db, reservation.id), Decimal("400")
            )

    # ── возврат ─────────────────────────────────────────────────────────

    async def test_release_returns_bonuses_exactly_once(self):
        await self._credit("400")
        reservation = await self._seed_reservation(quoted="1000.00")

        async with SessionLocal() as db:
            user = await db.get(User, self.user_id)
            fresh = await db.get(Reservation, reservation.id)
            await apply_bonus_spend(db, user=user, reservation=fresh, amount=Decimal("400"))
            await db.commit()

        # Точек отмены несколько (роут отмены, два шедулера) — каждая зовёт
        # release_bonus_spend, и вернуться бонусы должны ровно один раз.
        for _ in range(3):
            async with SessionLocal() as db:
                await release_bonus_spend(db, reservation_id=reservation.id)
                await db.commit()

        self.assertEqual(await self._balance(), Decimal("400.00"))
        async with SessionLocal() as db:
            self.assertEqual(
                await bonus_spent_for_reservation(db, reservation.id), Decimal("0")
            )

    async def test_expiry_of_unpaid_reservation_returns_bonuses(self):
        """Клиент ушёл со страницы ЮKassa: платежа нет, бонусы вернуть надо."""
        await self._credit("400")
        reservation = await self._seed_reservation(
            quoted="1000.00", expires_in=timedelta(hours=-1)
        )

        async with SessionLocal() as db:
            user = await db.get(User, self.user_id)
            fresh = await db.get(Reservation, reservation.id)
            await apply_bonus_spend(db, user=user, reservation=fresh, amount=Decimal("400"))
            await db.commit()

        self.assertEqual(await self._balance(), Decimal("0.00"))

        await expire_stale_reservations()
        await expire_stale_reservations()  # второй тик не должен вернуть повторно

        self.assertEqual(await self._balance(), Decimal("400.00"))
        async with SessionLocal() as db:
            fresh = await db.get(Reservation, reservation.id)
            self.assertEqual(fresh.status, ReservationStatus.EXPIRED)

    async def test_spent_bonuses_do_not_earn_new_bonuses(self):
        """Сквозной кейс: списал 400 из 1000 → начислено 42, а не 70."""
        await self._credit("400")
        reservation = await self._seed_reservation(quoted="1000.00")

        async with SessionLocal() as db:
            user = await db.get(User, self.user_id)
            fresh = await db.get(Reservation, reservation.id)
            await apply_bonus_spend(db, user=user, reservation=fresh, amount=Decimal("400"))
            await db.commit()

        # Картой ушло 600 ₽ — именно они и есть база начисления.
        rental = await self._seed_rental(reservation=reservation, paid_amount="600.00")
        async with SessionLocal() as db:
            fresh_rental = await db.get(Rental, rental.id)
            accrued = await accrue_rental_bonus(db, rental=fresh_rental)
            await db.commit()

        self.assertEqual(accrued, Decimal("42"))
        self.assertEqual(await self._balance(), Decimal("42.00"))

    # ── ручные операции админа ──────────────────────────────────────────

    async def test_admin_accrue_and_withdraw(self):
        async with SessionLocal() as db:
            applied, balance = await admin_adjust(
                db,
                user_id=self.user_id,
                amount=Decimal("500"),
                direction="accrue",
                admin_account_id=None,
                comment="компенсация за задержку",
            )
            await db.commit()
        self.assertEqual(applied, Decimal("500"))
        self.assertEqual(balance, Decimal("500.00"))

        async with SessionLocal() as db:
            _, balance = await admin_adjust(
                db,
                user_id=self.user_id,
                amount=Decimal("200"),
                direction="withdraw",
                admin_account_id=None,
                comment="ошибочное начисление",
            )
            await db.commit()
        self.assertEqual(balance, Decimal("300.00"))
        self.assertEqual(await self._balance(), Decimal("300.00"))

    async def test_admin_cannot_withdraw_more_than_balance(self):
        await self._credit("100")
        async with SessionLocal() as db:
            with self.assertRaises(BonusError) as ctx:
                await admin_adjust(
                    db,
                    user_id=self.user_id,
                    amount=Decimal("101"),
                    direction="withdraw",
                    admin_account_id=None,
                    comment="перебор",
                )
            self.assertEqual(ctx.exception.code, "BONUS_INSUFFICIENT_BALANCE")
        self.assertEqual(await self._balance(), Decimal("100.00"))

    async def test_admin_comment_is_required(self):
        async with SessionLocal() as db:
            with self.assertRaises(BonusError) as ctx:
                await admin_adjust(
                    db,
                    user_id=self.user_id,
                    amount=Decimal("100"),
                    direction="accrue",
                    admin_account_id=None,
                    comment="   ",
                )
            self.assertEqual(ctx.exception.code, "BONUS_COMMENT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
