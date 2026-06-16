"""Перевод сидовых постаматов в боевую конфигурацию.

Цель миграции (по запросу продакта):

- В Санкт-Петербурге:
  * `seed-spb-nevsky` остаётся как фейковый seed-постамат в статусе
    OFFLINE. Фронт фильтрует не-ONLINE точки и при выборе товара
    в Питере покажет EmptyState «Нет постаматов с этим товаром»;
  * `seed-spb-petrogradka` удаляется полностью со всеми связанными
    ячейками и пустыми inventory_units. Если к нему привязаны
    активные брони/аренды — миграция останавливается с ошибкой,
    чтобы не порушить чужие операции.
- В Великом Новгороде:
  * `seed-vn-center` становится "настоящим" — провайдер `esi`,
    `external_locker_id=0980`, статус ONLINE, partner_name=ESI;
  * `seed-vn-west` остаётся как seed-постамат, OFFLINE.

Скрипт идемпотентный: можно гонять сколько угодно раз, он только
приводит каждую сущность к целевому состоянию. Удаление Петроградки
тоже идемпотентно — повторный запуск просто ничего не находит.

Запуск:
    python -m scripts.migrate_lockers_to_real

Через docker compose на проде:
    docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml \\
        exec backend python -m scripts.migrate_lockers_to_real
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Поддерживаем запуск как `python -m scripts.migrate_lockers_to_real`
# и как `python scripts/migrate_lockers_to_real.py` из корня проекта.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.core.database import SessionLocal, engine  # noqa: E402
from backend.models.city import City  # noqa: E402
from backend.models.enums import (  # noqa: E402
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    RentalStatus,
    ReservationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.product import Product  # noqa: E402
from backend.models.rental import Rental  # noqa: E402
from backend.models.inventory_movement import InventoryMovement  # noqa: E402
from backend.models.condition_report import ConditionReport  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402
from backend.models.rental_event import RentalEvent  # noqa: E402
from backend.models.esi_event_log import EsiEventLog  # noqa: E402
from backend.models.payment import Payment  # noqa: E402
from backend.models.payment_event import PaymentEvent  # noqa: E402
from backend.models.return_request import ReturnRequest  # noqa: E402

# При flush SQLAlchemy строит граф таблиц по всем FK у моделей,
# зарегистрированных в Base.metadata. У ``LockerLocation`` есть
# ``ForeignKey("cities.id")`` — без явного импорта ``City`` ORM не
# находит таблицу ``cities`` и падает на ``commit()`` с
# ``NoReferencedTableError``. Подгружаем все модели по тому же
# списку, что использует ``alembic/env.py``, чтобы граф был полным
# и в любых будущих миграциях скрипту хватало контекста.
from backend.models import (  # noqa: E402, F401
    admin_account,
    admin_audit_event,
    admin_auth_session,
    admin_user,
    auth_session,
    auth_verification_session,
    city,
    condition_report,
    condition_report_photo,
    esi_event_log,
    inventory_movement,
    inventory_unit,
    locker_cell,
    media_file,
    payment,
    payment_event,
    price_plan,
    product,
    product_category,
    product_image,
    rental,
    rental_event,
    rental_idea,
    return_request,
    reservation,
    user,
    verification_request,
)


logger = logging.getLogger("migrate_lockers_to_real")


@dataclass(frozen=True)
class TargetState:
    match_provider: str
    match_external_id: str
    new_provider: str
    new_external_id: str
    new_status: LockerStatus
    new_partner_name: str
    new_name: str | None = None
    new_address: str | None = None


@dataclass(frozen=True)
class DeleteTarget:
    """Постамат, который нужно удалить вместе со всеми его ячейками
    и пустыми inventory_units. Если к нему привязаны активные брони
    или аренды — миграция остановится."""

    match_provider: str
    match_external_id: str


TARGETS: tuple[TargetState, ...] = (
    # СПб Невский — фейковая витрина: статус MAINTENANCE, чтобы товары
    # отображались в каталоге Питера, но кнопка «Оформить аренду» была
    # заблокирована (бэкенд при reservation вернёт LOCKER_NOT_BOOKABLE).
    TargetState(
        match_provider="seed",
        match_external_id="seed-spb-nevsky",
        new_provider="seed",
        new_external_id="seed-spb-nevsky",
        new_status=LockerStatus.MAINTENANCE,
        new_partner_name="Dev Seed",
    ),
    # В.Новгород Центр — настоящий ESI PST_0980. Серийник у провайдера
    # хранится с префиксом `PST_`, без префикса ESI отвечает 404.
    TargetState(
        match_provider="seed",
        match_external_id="seed-vn-center",
        new_provider="esi",
        new_external_id="PST_0980",
        new_status=LockerStatus.ONLINE,
        new_partner_name="ESI",
        new_name="Великий Новгород Центр",
        new_address="Великий Новгород, Большая Санкт-Петербургская ул., 39",
    ),
    # В.Новгород Западный — выключаем (seed, OFFLINE, остаётся в каталоге
    # как тестовая точка).
    TargetState(
        match_provider="seed",
        match_external_id="seed-vn-west",
        new_provider="seed",
        new_external_id="seed-vn-west",
        new_status=LockerStatus.OFFLINE,
        new_partner_name="Dev Seed",
    ),
)


# Постаматы, подлежащие полному удалению вместе с ячейками.
DELETE_TARGETS: tuple[DeleteTarget, ...] = (
    DeleteTarget(match_provider="seed", match_external_id="seed-spb-petrogradka"),
    DeleteTarget(match_provider="esi", match_external_id="test-moscow-fake-001"),
)


INVENTORY_SYNC_TARGETS: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    (("seed", "seed-spb-nevsky"), ("esi", "PST_0980")),
)


CITY_PRODUCT_REMOVALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("spb", ("perforator-elitech", "projektor")),
)


# Статусы броней/аренд, при которых удалять постамат опасно — это
# реальные пользовательские операции в полёте.
_ACTIVE_RESERVATION_STATUSES: frozenset[ReservationStatus] = frozenset(
    {
        ReservationStatus.CREATED,
        ReservationStatus.AWAITING_PAYMENT,
        ReservationStatus.PAYMENT_AUTHORIZED,
        ReservationStatus.CONFIRMED,
    }
)
_ACTIVE_RENTAL_STATUSES: frozenset[RentalStatus] = frozenset(
    {
        RentalStatus.PICKUP_READY,
        RentalStatus.PICKUP_OPENED,
        RentalStatus.ACTIVE,
        RentalStatus.RETURN_IN_PROGRESS,
        RentalStatus.OVERDUE,
        RentalStatus.INCIDENT,
    }
)
_DELETABLE_INVENTORY_STATUSES: frozenset[InventoryStatus] = frozenset(
    {
        InventoryStatus.AVAILABLE,
        InventoryStatus.DAMAGED,
        InventoryStatus.MAINTENANCE,
        InventoryStatus.LOST,
        InventoryStatus.RETIRED,
    }
)


async def _find_locker(session: AsyncSession, target: TargetState) -> LockerLocation | None:
    """Ищет локер по целевой паре, иначе по исходной.

    Это нужно, чтобы при повторных запусках мы находили уже
    промигрированный локер (например, `esi/0980`), а не создавали
    дубль и не падали "не нашёл".
    """

    locker = await session.scalar(
        select(LockerLocation).where(
            LockerLocation.external_provider == target.new_provider,
            LockerLocation.external_locker_id == target.new_external_id,
        )
    )
    if locker is not None:
        return locker

    return await session.scalar(
        select(LockerLocation).where(
            LockerLocation.external_provider == target.match_provider,
            LockerLocation.external_locker_id == target.match_external_id,
        )
    )


async def _load_products_by_slug(session: AsyncSession) -> dict[str, Product]:
    products = (await session.scalars(select(Product))).all()
    return {product.slug: product for product in products}


async def _locker_inventory_counts(session: AsyncSession, locker_id: object) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Product.slug, func.count(InventoryUnit.id).label("units"))
            .select_from(InventoryUnit)
            .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
            .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
            .join(Product, Product.id == InventoryUnit.product_id)
            .where(LockerLocation.id == locker_id)
            .group_by(Product.slug)
            .order_by(Product.slug.asc())
        )
    ).all()
    return {str(row.slug): int(row.units) for row in rows}


async def _locker_rebuild_blocker(session: AsyncSession, locker_id: object) -> str | None:
    if (
        await session.scalar(
            select(Reservation.id)
            .where(
                Reservation.locker_id == locker_id,
                Reservation.status.in_(_ACTIVE_RESERVATION_STATUSES),
            )
            .limit(1)
        )
    ) is not None:
        return "has_active_reservations"

    if (
        await session.scalar(
            select(Rental.id)
            .where(
                Rental.pickup_locker_id == locker_id,
                Rental.status.in_(_ACTIVE_RENTAL_STATUSES),
            )
            .limit(1)
        )
    ) is not None:
        return "has_active_rentals"

    cell_ids = list(
        (await session.scalars(select(LockerCell.id).where(LockerCell.locker_id == locker_id))).all()
    )
    if not cell_ids:
        return None

    units = list(
        (
            await session.scalars(select(InventoryUnit).where(InventoryUnit.locker_cell_id.in_(cell_ids)))
        ).all()
    )
    for unit in units:
        if unit.status not in _DELETABLE_INVENTORY_STATUSES:
            return f"inventory_unit_{unit.id}_status_{unit.status.value}"
    return None


async def _sync_locker_inventory_from_source(
    session: AsyncSession,
    *,
    source_locker: LockerLocation,
    target_locker: LockerLocation,
    products_by_slug: dict[str, Product],
) -> bool:
    source_inventory = await _locker_inventory_counts(session, source_locker.id)
    target_inventory = await _locker_inventory_counts(session, target_locker.id)
    if source_inventory == target_inventory:
        return False

    blocker = await _locker_rebuild_blocker(session, target_locker.id)
    if blocker is not None:
        logger.warning(
            "Skip inventory sync source=%s/%s target=%s/%s blocker=%s",
            source_locker.external_provider,
            source_locker.external_locker_id,
            target_locker.external_provider,
            target_locker.external_locker_id,
            blocker,
        )
        return False

    existing_cell_ids = list(
        (
            await session.scalars(select(LockerCell.id).where(LockerCell.locker_id == target_locker.id))
        ).all()
    )
    if existing_cell_ids:
        await session.execute(
            delete(InventoryUnit).where(InventoryUnit.locker_cell_id.in_(existing_cell_ids))
        )
        await session.execute(delete(LockerCell).where(LockerCell.id.in_(existing_cell_ids)))
        await session.flush()

    index = 1
    for product_slug, count in source_inventory.items():
        product = products_by_slug.get(product_slug)
        if product is None:
            raise RuntimeError(
                f"Product slug not found while syncing locker inventory: {product_slug}"
            )
        for unit_number in range(1, count + 1):
            cell = LockerCell(
                locker_id=target_locker.id,
                external_cell_id=f"{target_locker.external_locker_id}-cell-{index:02d}",
                label=f"A{index}",
                size="M",
                status=LockerCellStatus.OCCUPIED,
                supports_return=True,
            )
            session.add(cell)
            await session.flush()

            unit = InventoryUnit(
                product_id=product.id,
                locker_cell_id=cell.id,
                serial_number=f"{target_locker.external_locker_id.upper()}-{product.slug.upper()}-{unit_number}",
                barcode=f"{target_locker.external_locker_id}-{product.slug}-{unit_number}",
                status=InventoryStatus.AVAILABLE,
                condition_grade="A",
                condition_note="Готов к аренде",
            )
            session.add(unit)
            index += 1

    for empty_index in range(2):
        session.add(
            LockerCell(
                locker_id=target_locker.id,
                external_cell_id=f"{target_locker.external_locker_id}-empty-{empty_index + 1}",
                label=f"B{empty_index + 1}",
                size="L",
                status=LockerCellStatus.VACANT,
                supports_return=True,
            )
        )

    logger.info(
        "Synced inventory source=%s/%s target=%s/%s product_types=%s",
        source_locker.external_provider,
        source_locker.external_locker_id,
        target_locker.external_provider,
        target_locker.external_locker_id,
        len(source_inventory),
    )
    return True


async def _remove_products_from_city(
    session: AsyncSession,
    *,
    city_slug: str,
    product_slugs: tuple[str, ...],
) -> int:
    rows = (
        await session.execute(
            select(InventoryUnit, LockerCell)
            .select_from(InventoryUnit)
            .join(LockerCell, InventoryUnit.locker_cell_id == LockerCell.id)
            .join(LockerLocation, LockerCell.locker_id == LockerLocation.id)
            .join(City, LockerLocation.city_id == City.id)
            .join(Product, Product.id == InventoryUnit.product_id)
            .where(City.slug == city_slug, Product.slug.in_(product_slugs))
        )
    ).all()
    removed = 0
    for unit, cell in rows:
        if unit.status not in _DELETABLE_INVENTORY_STATUSES:
            logger.warning(
                "Skip product removal city=%s product_unit=%s status=%s",
                city_slug,
                unit.id,
                unit.status.value,
            )
            continue
        await session.delete(unit)
        await session.flush()
        await session.delete(cell)
        removed += 1
    if removed:
        logger.info(
            "Removed city products city=%s slugs=%s units=%s",
            city_slug,
            ",".join(product_slugs),
            removed,
        )
    return removed


def _apply_target(locker: LockerLocation, target: TargetState) -> bool:
    """Применяет целевое состояние. Возвращает True, если что-то поменялось."""

    changed = False
    if locker.external_provider != target.new_provider:
        locker.external_provider = target.new_provider
        changed = True
    if locker.external_locker_id != target.new_external_id:
        locker.external_locker_id = target.new_external_id
        changed = True
    if locker.status != target.new_status:
        locker.status = target.new_status
        changed = True
    if locker.partner_name != target.new_partner_name:
        locker.partner_name = target.new_partner_name
        changed = True
    if target.new_name and locker.name != target.new_name:
        locker.name = target.new_name
        changed = True
    if target.new_address and locker.address != target.new_address:
        locker.address = target.new_address
        changed = True
    return changed


async def _delete_locker_cascade(
    session: AsyncSession, target: DeleteTarget
) -> tuple[bool, str]:
    """Удаляет постамат вместе с ячейками и пустыми inventory_units.

    Возвращает (deleted, reason). ``deleted=True`` означает, что точка
    была найдена и удалена. ``deleted=False`` + reason описывает, почему
    миграция должна остановиться (есть активные брони/аренды) или почему
    удалять было нечего (точку уже удалили раньше).
    """

    locker = await session.scalar(
        select(LockerLocation).where(
            LockerLocation.external_provider == target.match_provider,
            LockerLocation.external_locker_id == target.match_external_id,
        )
    )
    if locker is None:
        return False, "not_found"

    cell_ids = list(
        (
            await session.scalars(
                select(LockerCell.id).where(LockerCell.locker_id == locker.id)
            )
        ).all()
    )

    # Защита: активные брони на этом постамате.
    if (
        await session.scalar(
            select(Reservation.id)
            .where(
                Reservation.locker_id == locker.id,
                Reservation.status.in_(_ACTIVE_RESERVATION_STATUSES),
            )
            .limit(1)
        )
    ) is not None:
        return False, "has_active_reservations"

    # Защита: активные аренды на этом постамате.
    rental_by_locker = await session.scalar(
        select(Rental.id)
        .where(
            Rental.pickup_locker_id == locker.id,
            Rental.status.in_(_ACTIVE_RENTAL_STATUSES),
        )
        .limit(1)
    )
    if rental_by_locker is not None:
        return False, "has_active_rentals"

    # Inventory_units, которые сейчас лежат в ячейках этого постамата.
    if cell_ids:
        units = list(
            (
                await session.scalars(
                    select(InventoryUnit).where(
                        InventoryUnit.locker_cell_id.in_(cell_ids)
                    )
                )
            ).all()
        )
        for unit in units:
            if unit.status not in _DELETABLE_INVENTORY_STATUSES:
                return False, f"inventory_unit_{unit.id}_status_{unit.status.value}"
        # Удаляем полностью — точка уходит навсегда, привязывать к другой
        # ячейке некуда. Это безопасно благодаря проверкам выше.
        unit_ids = [u.id for u in units]
        if unit_ids:
            rentals_list = (await session.scalars(select(Rental.id).where(Rental.inventory_unit_id.in_(unit_ids)))).all()
            if rentals_list:
                return_reqs = (await session.scalars(select(ReturnRequest.id).where(ReturnRequest.rental_id.in_(rentals_list)))).all()
                if return_reqs:
                    await session.execute(delete(EsiEventLog).where(EsiEventLog.matched_return_request_id.in_(return_reqs)))
                await session.execute(delete(ReturnRequest).where(ReturnRequest.rental_id.in_(rentals_list)))
                
                payments = (await session.scalars(select(Payment.id).where(Payment.rental_id.in_(rentals_list)))).all()
                if payments:
                    await session.execute(delete(PaymentEvent).where(PaymentEvent.payment_id.in_(payments)))
                await session.execute(delete(Payment).where(Payment.rental_id.in_(rentals_list)))
                
                await session.execute(delete(EsiEventLog).where(EsiEventLog.matched_rental_id.in_(rentals_list)))
                await session.execute(delete(RentalEvent).where(RentalEvent.rental_id.in_(rentals_list)))
                await session.execute(delete(ConditionReport).where(ConditionReport.rental_id.in_(rentals_list)))
                await session.execute(delete(Rental).where(Rental.id.in_(rentals_list)))

            reservations_list = (await session.scalars(select(Reservation.id).where(Reservation.inventory_unit_id.in_(unit_ids)))).all()
            if reservations_list:
                payments_res = (await session.scalars(select(Payment.id).where(Payment.reservation_id.in_(reservations_list)))).all()
                if payments_res:
                    await session.execute(delete(PaymentEvent).where(PaymentEvent.payment_id.in_(payments_res)))
                await session.execute(delete(Payment).where(Payment.reservation_id.in_(reservations_list)))
                await session.execute(delete(Reservation).where(Reservation.id.in_(reservations_list)))

            await session.execute(delete(InventoryMovement).where(InventoryMovement.inventory_unit_id.in_(unit_ids)))
            await session.execute(delete(ConditionReport).where(ConditionReport.inventory_unit_id.in_(unit_ids)))
        for unit in units:
            await session.delete(unit)
        await session.flush()

    # Удаляем все ячейки этого постамата, потом сам постамат.
    if cell_ids:
        await session.execute(delete(LockerCell).where(LockerCell.id.in_(cell_ids)))
    await session.delete(locker)
    return True, "deleted"


async def _run() -> int:
    updates = 0
    skipped = 0
    missing = 0
    deleted = 0
    delete_skipped = 0

    async with SessionLocal() as session:
        products_by_slug = await _load_products_by_slug(session)

        for target in TARGETS:
            locker = await _find_locker(session, target)
            if locker is None:
                missing += 1
                logger.warning(
                    "Locker not found: provider=%s external_id=%s — skip",
                    target.match_provider,
                    target.match_external_id,
                )
                continue

            if _apply_target(locker, target):
                updates += 1
                logger.info(
                    "Updated locker %s -> provider=%s external_id=%s status=%s",
                    locker.id,
                    target.new_provider,
                    target.new_external_id,
                    target.new_status.value,
                )
            else:
                skipped += 1
                logger.info(
                    "Locker already in target state: provider=%s external_id=%s",
                    target.new_provider,
                    target.new_external_id,
                )

        for city_slug, product_slugs in CITY_PRODUCT_REMOVALS:
            updates += await _remove_products_from_city(
                session,
                city_slug=city_slug,
                product_slugs=product_slugs,
            )

        for (source_provider, source_external_id), (target_provider, target_external_id) in INVENTORY_SYNC_TARGETS:
            source_locker = await session.scalar(
                select(LockerLocation).where(
                    LockerLocation.external_provider == source_provider,
                    LockerLocation.external_locker_id == source_external_id,
                )
            )
            target_locker = await session.scalar(
                select(LockerLocation).where(
                    LockerLocation.external_provider == target_provider,
                    LockerLocation.external_locker_id == target_external_id,
                )
            )
            if source_locker is None or target_locker is None:
                missing += int(source_locker is None) + int(target_locker is None)
                logger.warning(
                    "Inventory sync skipped: source=%s/%s target=%s/%s",
                    source_provider,
                    source_external_id,
                    target_provider,
                    target_external_id,
                )
                continue
            if await _sync_locker_inventory_from_source(
                session,
                source_locker=source_locker,
                target_locker=target_locker,
                products_by_slug=products_by_slug,
            ):
                updates += 1

        for delete_target in DELETE_TARGETS:
            ok, reason = await _delete_locker_cascade(session, delete_target)
            if ok:
                deleted += 1
                logger.info(
                    "Deleted locker provider=%s external_id=%s",
                    delete_target.match_provider,
                    delete_target.match_external_id,
                )
            elif reason == "not_found":
                delete_skipped += 1
                logger.info(
                    "Locker provider=%s external_id=%s already absent — skip",
                    delete_target.match_provider,
                    delete_target.match_external_id,
                )
            else:
                # Активные операции на постамате — отказываемся удалять,
                # откатываем всю транзакцию, чтобы не получился
                # частично применённый перевод.
                await session.rollback()
                await engine.dispose()
                logger.error(
                    "Refuse to delete locker provider=%s external_id=%s: %s",
                    delete_target.match_provider,
                    delete_target.match_external_id,
                    reason,
                )
                return 1

        await session.commit()

    await engine.dispose()

    logger.info(
        "Migration finished: updated=%s up_to_date=%s missing=%s deleted=%s "
        "delete_skipped=%s",
        updates,
        skipped,
        missing,
        deleted,
        delete_skipped,
    )
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
