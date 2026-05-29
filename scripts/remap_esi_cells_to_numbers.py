"""Привязка external_cell_id наших ячеек к номерам ячеек ESI (1..N).

Зачем: команды открытия идут на ``/open-cell/{serial}/{external_cell_id}``.
ESI ожидает в качестве cell id физический номер ячейки (``1``..``N`` из
снапшота ``/machine/{serial}``). Если у наших ячеек ``external_cell_id``
заданы сид/импорт-строками (``seed-...``, ``PST_0980-import-...``), ESI
отвечает 404 и открытие падает (ESI_CELL_OR_MACHINE_NOT_FOUND).

Что делает скрипт:
1. Берёт постамат по ``--locker`` (external_locker_id, по умолчанию
   ``PST_0980``).
2. Запрашивает у ESI снапшот и собирает реальные номера ячеек.
3. Сопоставляет наши ячейки с номерами ESI в «естественном» порядке
   меток (A1, A2, A3, B1, B2, C1, C2, I8, I9, I10, I11, I12 → 1..12) —
   так числовые метки I8..I12 ложатся на ESI 8..12.
4. По умолчанию (dry-run) только печатает предлагаемый маппинг.
   С флагом ``--apply`` записывает ``external_cell_id = <номер ESI>``.

ВАЖНО (физический риск): открытие ячейки физически отпирает дверцу.
Перед ``--apply`` сверьте предложенный маппинг с реальностью — особенно
строки A/B/C, где числовой подсказки в метке нет. Запускать строго
при операторе у постамата.

Скрипт меняет ТОЛЬКО external_cell_id ячеек. Он НЕ трогает инвентарь,
статусы занятости и не шлёт команды открытия.

Запуск (dry-run):
    docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml \\
        exec backend python -m scripts.remap_esi_cells_to_numbers

Применить:
    ... exec backend python -m scripts.remap_esi_cells_to_numbers --apply

Явный маппинг (если естественный порядок не подходит):
    ... python -m scripts.remap_esi_cells_to_numbers \\
        --map "A1=1,A2=2,A3=3,B1=4,B2=5,C1=6,C2=7,I8=8,I9=9,I10=10,I11=11,I12=12" --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
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
)


def _natural_key(label: str) -> tuple:
    """Натуральная сортировка меток: A1<A2<A3<B1<...<I8<I9<I10<I11<I12.

    Разбиваем на (буквенный префикс, числовой суффикс), число сортируем
    как int, чтобы I10 шёл после I9, а не после I1.
    """
    s = (label or "").strip()
    m = re.match(r"^([A-Za-zА-Яа-я]*)(\d*)$", s)
    if not m:
        return (s, 0)
    prefix, num = m.group(1), m.group(2)
    return (prefix.upper(), int(num) if num else 0)


def _extract_esi_cell_ids(snapshot: dict | None) -> list[str]:
    if not isinstance(snapshot, dict):
        return []
    cells = snapshot.get("cells")
    if not isinstance(cells, dict):
        return []
    ids = [str(k) for k, v in cells.items() if isinstance(v, dict)]
    # Сортируем номера численно, где возможно.
    def key(x: str):
        return (0, int(x)) if x.isdigit() else (1, x)
    return sorted(ids, key=key)


def _parse_explicit_map(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise SystemExit(f"Bad --map entry (no '='): {pair!r}")
        label, value = pair.split("=", 1)
        out[label.strip().upper()] = value.strip()
    return out


async def _run(locker_external_id: str, apply: bool, explicit_map: dict[str, str]) -> int:
    if settings.ESI_DEV_STUB:
        print("ESI_DEV_STUB=true — нет реальной машины для сверки. Выходим.")
        return 1
    if not settings.ESI_BASE_URL:
        print("ESI_BASE_URL не задан. Выходим.")
        return 1

    async with SessionLocal() as session:
        locker = await session.scalar(
            select(LockerLocation).where(
                LockerLocation.external_locker_id == locker_external_id
            )
        )
        if locker is None:
            print(f"Постамат с external_locker_id={locker_external_id!r} не найден.")
            await engine.dispose()
            return 1

        cells = list(
            (
                await session.scalars(
                    select(LockerCell).where(LockerCell.locker_id == locker.id)
                )
            ).all()
        )
        if not cells:
            print("У постамата нет ячеек.")
            await engine.dispose()
            return 1

        try:
            snapshot = await fetch_machine_snapshot(locker_external_id)
        except EsiDiscoveryError as exc:
            print(f"Не удалось получить снапшот ESI: {exc}")
            await engine.dispose()
            return 1

        esi_ids = _extract_esi_cell_ids(snapshot)
        if not esi_ids:
            print(f"ESI не вернул ячейки для serial={locker_external_id!r}.")
            await engine.dispose()
            return 1

        cells_sorted = sorted(cells, key=lambda c: _natural_key(c.label or ""))

        # Строим маппинг label -> esi_id.
        mapping: dict[str, str] = {}
        if explicit_map:
            mapping = explicit_map
        else:
            if len(cells_sorted) != len(esi_ids):
                print(
                    f"[ОТКАЗ] Число наших ячеек ({len(cells_sorted)}) != числу "
                    f"ячеек ESI ({len(esi_ids)}). Автосопоставление по порядку "
                    "небезопасно — задайте явный --map."
                )
                await engine.dispose()
                return 1
            for cell, esi_id in zip(cells_sorted, esi_ids):
                mapping[(cell.label or "").strip().upper()] = esi_id

        # Проверки маппинга: целевые id существуют у ESI и уникальны.
        targets = list(mapping.values())
        if len(set(targets)) != len(targets):
            print(f"[ОТКАЗ] В маппинге есть повторяющиеся номера ESI: {targets}")
            await engine.dispose()
            return 1
        unknown = [t for t in targets if t not in esi_ids]
        if unknown:
            print(f"[ОТКАЗ] Номера, которых нет у ESI: {unknown}. Доступны: {esi_ids}")
            await engine.dispose()
            return 1

        print(f"Постамат {locker.name!r} (serial={locker_external_id!r})")
        print(f"Ячейки ESI: {', '.join(esi_ids)}")
        print("-" * 70)
        print(f"{'label':>6}  {'current external_cell_id':40}  -> ESI")
        changed = 0
        for cell in cells_sorted:
            label = (cell.label or "").strip().upper()
            target = mapping.get(label)
            if target is None:
                print(f"{label:>6}  {str(cell.external_cell_id):40}  -> (нет в маппинге, пропуск)")
                continue
            mark = "" if str(cell.external_cell_id) == target else "  *"
            print(f"{label:>6}  {str(cell.external_cell_id):40}  -> {target}{mark}")
            if str(cell.external_cell_id) != target:
                changed += 1
                if apply:
                    cell.external_cell_id = target

        print("-" * 70)
        if not apply:
            print(
                f"DRY-RUN. К изменению: {changed} ячеек. Запустите с --apply, "
                "когда сверите маппинг (особенно строки A/B/C)."
            )
            await engine.dispose()
            return 0

        if changed:
            await session.commit()
            print(f"Готово: обновлено {changed} ячеек.")
        else:
            print("Изменений нет — всё уже привязано.")

    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Remap locker cells external_cell_id to ESI numbers")
    parser.add_argument("--locker", default="PST_0980", help="external_locker_id постамата")
    parser.add_argument("--apply", action="store_true", help="применить изменения (по умолчанию dry-run)")
    parser.add_argument("--map", dest="explicit_map", default=None, help="явный маппинг 'A1=1,A2=2,...'")
    args = parser.parse_args()
    explicit = _parse_explicit_map(args.explicit_map)
    return asyncio.run(_run(args.locker, args.apply, explicit))


if __name__ == "__main__":
    raise SystemExit(main())
