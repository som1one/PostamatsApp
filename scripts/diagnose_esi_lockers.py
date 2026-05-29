"""Диагностика рассинхрона ESI-постаматов (только чтение).

Для каждого постамата с ``external_provider="esi"`` скрипт:

1. Берёт его ``external_locker_id`` (serial) и ячейки из нашей БД.
2. Запрашивает у ESI снапшот ``/machine/{serial}``.
3. Печатает рядом наши ячейки (``external_cell_id`` / label) и реальные
   ячейки ESI (номера ``1..N`` со state/pin/open).
4. Подсвечивает проблемы:
   - serial неизвестен ESI (``/machine`` → 404 / пусто) — постамат не
     привязан под этим идентификатором;
   - наши ``external_cell_id`` не совпадают с номерами ESI — открытие
     ячеек будет падать с ESI_CELL_OR_MACHINE_NOT_FOUND.

Скрипт НИЧЕГО не меняет: ни в БД, ни в постамате (не шлёт open-cell).
Безопасно гонять на проде сколько угодно раз.

Запуск:
    python -m scripts.diagnose_esi_lockers

Через docker compose на проде:
    docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml \\
        exec backend python -m scripts.diagnose_esi_lockers
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import select

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.core.settings import settings  # noqa: E402
from backend.core.database import SessionLocal, engine  # noqa: E402
from backend.models.locker_cell import LockerCell  # noqa: E402
from backend.models.locker_location import LockerLocation  # noqa: E402
from backend.utils.esi_client import (  # noqa: E402
    EsiDiscoveryError,
    fetch_machine_snapshot,
    fetch_machines_snapshot,
)


def _extract_cells(snapshot: dict | None) -> dict[str, dict]:
    if not isinstance(snapshot, dict):
        return {}
    cells = snapshot.get("cells")
    if isinstance(cells, dict):
        return {str(k): v for k, v in cells.items() if isinstance(v, dict)}
    return {}


async def _run() -> int:
    if settings.ESI_DEV_STUB:
        print("ESI_DEV_STUB=true — реальные машины не опрашиваются. Выходим.")
        return 0
    if not settings.ESI_BASE_URL:
        print("ESI_BASE_URL не задан. Выходим.")
        return 1

    # Список всех известных провайдеру машин — для подсказки, если serial
    # в БД не совпадает (например, 0980 vs PST_0980).
    known_serials: list[str] = []
    try:
        machines = await fetch_machines_snapshot()
        for m in machines:
            serial = m.get("serial") or m.get("id") or m.get("lockerId")
            if serial:
                known_serials.append(str(serial))
    except EsiDiscoveryError as exc:
        print(f"Не удалось получить список машин ESI: {exc}")

    if known_serials:
        print("Машины, известные ESI: " + ", ".join(sorted(known_serials)))
    print("-" * 70)

    problems = 0
    async with SessionLocal() as session:
        lockers = (
            await session.scalars(
                select(LockerLocation).where(
                    LockerLocation.external_provider == "esi"
                )
            )
        ).all()

        if not lockers:
            print("В БД нет постаматов с провайдером 'esi'.")
            await engine.dispose()
            return 0

        for locker in lockers:
            serial = (locker.external_locker_id or "").strip()
            print(f"Постамат {locker.name!r} (serial={serial!r}, status={locker.status.value})")

            cells = (
                await session.scalars(
                    select(LockerCell)
                    .where(LockerCell.locker_id == locker.id)
                    .order_by(LockerCell.label.asc())
                )
            ).all()
            print(f"  Наши ячейки ({len(cells)}):")
            for c in cells:
                print(f"    label={c.label!r:>6}  external_cell_id={c.external_cell_id!r}  status={c.status.value}")

            snapshot = None
            try:
                snapshot = await fetch_machine_snapshot(serial)
            except EsiDiscoveryError as exc:
                print(f"  ESI snapshot error: {exc}")

            esi_cells = _extract_cells(snapshot)
            if not esi_cells:
                problems += 1
                print(
                    f"  [ПРОБЛЕМА] ESI не знает serial {serial!r} или не вернул ячейки."
                )
                if known_serials:
                    print(
                        "             Возможный правильный serial из /machines: "
                        + ", ".join(sorted(known_serials))
                    )
            else:
                esi_ids = sorted(esi_cells.keys(), key=lambda x: (len(x), x))
                print(f"  Ячейки ESI ({len(esi_cells)}): " + ", ".join(esi_ids))
                our_ids = {(c.external_cell_id or "").strip() for c in cells}
                matched = our_ids.intersection(set(esi_cells.keys()))
                if not matched:
                    problems += 1
                    print(
                        "  [ПРОБЛЕМА] Ни один наш external_cell_id не совпадает с "
                        "номерами ESI — команды открытия будут падать. Нужна "
                        "сверка и привязка ячеек к номерам ESI."
                    )
                elif len(matched) < len(cells):
                    print(
                        f"  [ВНИМАНИЕ] Совпали {len(matched)} из {len(cells)} ячеек."
                    )
            print("-" * 70)

    await engine.dispose()
    if problems:
        print(f"Найдено проблемных постаматов: {problems}")
    else:
        print("Рассинхронов не обнаружено.")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
