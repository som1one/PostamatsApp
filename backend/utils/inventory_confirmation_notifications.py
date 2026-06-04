from __future__ import annotations

from urllib.parse import urlencode

from backend.core.settings import settings
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.rental import Rental
from backend.utils.telegram_bot import escape_html, fire_and_forget_notify


def _build_inventory_admin_link(locker_id, cell_id) -> str | None:
    base = settings.ADMIN_PANEL_URL
    if not base:
        return None
    query = urlencode(
        {
            "section": "inventory",
            "locker": str(locker_id),
            "cell": str(cell_id),
        }
    )
    return f"{base.rstrip('/')}/?{query}"


def notify_inventory_awaiting_confirmation(
    *,
    product: Product,
    locker: LockerLocation,
    cell: LockerCell,
    unit: InventoryUnit,
    rental: Rental,
) -> None:
    cell_label = (cell.label or cell.external_cell_id or str(cell.id)).strip()
    serial_label = unit.serial_number or unit.barcode or str(unit.id)
    lines = [
        f"⏳ <b>Товар {escape_html(product.name)} ожидает подтверждения</b>",
        f"📍 {escape_html(locker.name)} · ячейка {escape_html(cell_label)}",
        f"🔖 {escape_html(serial_label)}",
        f"🧾 Аренда {escape_html(str(rental.id))}",
    ]

    buttons: list[tuple[str, str]] = []
    admin_link = _build_inventory_admin_link(locker.id, cell.id)
    if admin_link:
        buttons.append(("Открыть в админке", admin_link))

    fire_and_forget_notify("\n".join(lines), buttons=buttons)
