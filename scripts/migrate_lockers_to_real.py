"""Перевод сидовых постаматов в боевую конфигурацию.

Цель миграции (по запросу продакта):

- В Санкт-Петербурге остаётся один постамат, оба переводятся в OFFLINE
  (`seed-spb-nevsky`, `seed-spb-petrogradka`).
- В Великом Новгороде остаётся два постамата:
  * `seed-vn-center` становится "настоящим" — провайдер `esi`,
    `external_locker_id=0980`, статус ONLINE, partner_name=ESI.
  * `seed-vn-west` переводится в OFFLINE.

Скрипт идемпотентный: можно гонять сколько угодно раз, он только
приводит каждую сущность к целевому состоянию.

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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Поддерживаем запуск как `python -m scripts.migrate_lockers_to_real`
# и как `python scripts/migrate_lockers_to_real.py` из корня проекта.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.core.database import SessionLocal, engine  # noqa: E402
from backend.models.enums import LockerStatus  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402


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


TARGETS: tuple[TargetState, ...] = (
    # СПб: оба постамата выключаем.
    TargetState(
        match_provider="seed",
        match_external_id="seed-spb-nevsky",
        new_provider="seed",
        new_external_id="seed-spb-nevsky",
        new_status=LockerStatus.OFFLINE,
        new_partner_name="Dev Seed",
    ),
    TargetState(
        match_provider="seed",
        match_external_id="seed-spb-petrogradka",
        new_provider="seed",
        new_external_id="seed-spb-petrogradka",
        new_status=LockerStatus.OFFLINE,
        new_partner_name="Dev Seed",
    ),
    # В.Новгород Центр — настоящий ESI 0980.
    TargetState(
        match_provider="seed",
        match_external_id="seed-vn-center",
        new_provider="esi",
        new_external_id="0980",
        new_status=LockerStatus.ONLINE,
        new_partner_name="ESI",
        new_name="Великий Новгород Центр",
        new_address="Великий Новгород, Большая Санкт-Петербургская ул., 39",
    ),
    # В.Новгород Западный — выключаем.
    TargetState(
        match_provider="seed",
        match_external_id="seed-vn-west",
        new_provider="seed",
        new_external_id="seed-vn-west",
        new_status=LockerStatus.OFFLINE,
        new_partner_name="Dev Seed",
    ),
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


async def _run() -> int:
    updates = 0
    skipped = 0
    missing = 0

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

        await session.commit()

    await engine.dispose()

    logger.info(
        "Migration finished: updated=%s up_to_date=%s missing=%s",
        updates,
        skipped,
        missing,
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
