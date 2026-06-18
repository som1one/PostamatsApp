"""Приводит сид-постаматы в bundle к нужному состоянию.

- `seed-vn-west` (фейковый Великий Новгород): без ячеек и инвентаря,
  статус OFFLINE. Раньше там лежали тестовые товары, по которым
  на проде зависала оплата.
- `seed-spb-nevsky` (единственный СПб): ровно тот же набор товаров,
  что в реальном новгородском `esi/PST_0980` — 1:1 по slug'ам и количеству.

Скрипт идемпотентный: ходит по bundle, удаляет всё связанное с
этими двумя локерами и пересобирает СПб как зеркало PST_0980.
"""

import json
from pathlib import Path

BUNDLE_PATH = Path("deploy/catalog-sync.bundle.json")

VN_WEST_LOCKER = "seed-vn-west"
SPB_NEVSKY_LOCKER = "seed-spb-nevsky"
SPB_NEVSKY_PROVIDER = "seed"
SOURCE_LOCKER = "PST_1234"


def _is_locker_cell(cell: dict, locker_id: str) -> bool:
    return cell.get("lockerExternalLockerId") == locker_id


def _is_locker_unit(unit: dict, locker_id: str) -> bool:
    return unit.get("lockerExternalLockerId") == locker_id


def main() -> None:
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))

    # 1. seed-vn-west: убираем все ячейки/юниты, гасим в OFFLINE.
    for locker in bundle["lockers"]:
        if locker.get("externalLockerId") == VN_WEST_LOCKER:
            locker["status"] = "OFFLINE"
    bundle["cells"] = [
        cell for cell in bundle["cells"] if not _is_locker_cell(cell, VN_WEST_LOCKER)
    ]
    bundle["inventoryUnits"] = [
        unit for unit in bundle["inventoryUnits"] if not _is_locker_unit(unit, VN_WEST_LOCKER)
    ]

    # 2. seed-spb-nevsky: полная зачистка + зеркало PST_0980.
    bundle["cells"] = [
        cell for cell in bundle["cells"] if not _is_locker_cell(cell, SPB_NEVSKY_LOCKER)
    ]
    bundle["inventoryUnits"] = [
        unit for unit in bundle["inventoryUnits"] if not _is_locker_unit(unit, SPB_NEVSKY_LOCKER)
    ]

    pst_cells = [cell for cell in bundle["cells"] if _is_locker_cell(cell, SOURCE_LOCKER)]
    pst_units = [unit for unit in bundle["inventoryUnits"] if _is_locker_unit(unit, SOURCE_LOCKER)]

    # Сопоставление старой ячейки PST → новой ячейки СПб, чтобы units
    # после копирования указывали на правильную пару (externalCellId, label).
    cell_id_remap: dict[str, str] = {}
    cell_label_remap: dict[str, str] = {}

    new_spb_cells = []
    for cell in pst_cells:
        new_cell = cell.copy()
        new_cell["lockerExternalProvider"] = SPB_NEVSKY_PROVIDER
        new_cell["lockerExternalLockerId"] = SPB_NEVSKY_LOCKER

        old_external_id = cell["externalCellId"]
        new_external_id = f"{SPB_NEVSKY_LOCKER}-mirror-{old_external_id}"
        new_cell["externalCellId"] = new_external_id

        new_label = f"M-{cell['label']}"
        new_cell["label"] = new_label

        cell_id_remap[old_external_id] = new_external_id
        cell_label_remap[old_external_id] = new_label
        new_spb_cells.append(new_cell)

    bundle["cells"].extend(new_spb_cells)

    new_spb_units = []
    for idx, unit in enumerate(pst_units):
        new_unit = unit.copy()
        new_unit["lockerExternalProvider"] = SPB_NEVSKY_PROVIDER
        new_unit["lockerExternalLockerId"] = SPB_NEVSKY_LOCKER

        old_cell_id = unit["cellExternalCellId"]
        if old_cell_id in cell_id_remap:
            new_unit["cellExternalCellId"] = cell_id_remap[old_cell_id]
            new_unit["cellLabel"] = cell_label_remap[old_cell_id]

        # serial/barcode уникальны по БД — префиксуем, чтобы не конфликтовать
        # с оригинальными в PST_0980.
        if new_unit.get("serialNumber"):
            new_unit["serialNumber"] = f"SEED-SPB-NEVSKY-MIRROR-{idx}-{new_unit['serialNumber']}"
        if new_unit.get("barcode"):
            new_unit["barcode"] = f"seed-spb-nevsky-mirror-{idx}-{new_unit['barcode']}"

        new_spb_units.append(new_unit)

    bundle["inventoryUnits"].extend(new_spb_units)

    BUNDLE_PATH.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
