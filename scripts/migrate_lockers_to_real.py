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

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

# Поддерживаем запуск как `python -m scripts.migrate_lockers_to_real`
# и как `python scripts/migrate_lockers_to_real.py` из корня проекта.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.core.database import SessionLocal, engine  # noqa: E402
from backend.models.enums import (  # noqa: E402
    InventoryStatus,
    LockerStatus,
    RentalStatus,
    ReservationStatus,
)
from backend.models.inventory_unit import InventoryUnit  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.models.rental import Rental  # noqa: E402
from backend.models.reservation import Reservation  # noqa: E402

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
        for unit in units:
            await session.delete(unit)

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
