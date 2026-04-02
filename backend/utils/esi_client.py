import logging
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.enums import LockerCellStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell

logger = logging.getLogger(__name__)


class EsiReserveError(Exception):
    pass


async def reserve_pickup_cell(
    db: AsyncSession,
    *,
    locker_id: UUID,
    inventory_unit_id: UUID,
    reservation_id: UUID,
) -> None:
    unit = await db.get(InventoryUnit, inventory_unit_id)
    if unit is None or unit.locker_cell_id is None:
        raise EsiReserveError("INVENTORY_CELL_MISSING")

    cell = await db.get(LockerCell, unit.locker_cell_id)
    if cell is None or cell.locker_id != locker_id:
        raise EsiReserveError("LOCKER_CELL_MISMATCH")

    if cell.status in (LockerCellStatus.FAULT, LockerCellStatus.DISABLED):
        raise EsiReserveError("CELL_NOT_RESERVABLE")

    if settings.ESI_DEV_STUB:
        if cell.status == LockerCellStatus.VACANT:
            cell.status = LockerCellStatus.RESERVED
        await db.flush()
        return

    if not settings.ESI_BASE_URL:
        raise EsiReserveError("ESI_NOT_CONFIGURED")

    url = f"{settings.ESI_BASE_URL}/cells/reserve"
    headers = {}
    if settings.ESI_API_KEY:
        headers["Authorization"] = f"Bearer {settings.ESI_API_KEY}"

    payload = {
        "lockerId": str(locker_id),
        "cellId": str(cell.id),
        "externalCellId": cell.external_cell_id,
        "inventoryUnitId": str(inventory_unit_id),
        "reservationId": str(reservation_id),
    }

    try:
        async with httpx.AsyncClient(timeout=settings.ESI_RESERVE_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        logger.exception("ESI HTTP error")
        raise EsiReserveError("ESI_HTTP_ERROR") from exc

    if resp.status_code >= 400:
        logger.warning("ESI reserve failed: %s %s", resp.status_code, resp.text)
        raise EsiReserveError("ESI_RESERVE_FAILED")

    if cell.status == LockerCellStatus.VACANT:
        cell.status = LockerCellStatus.RESERVED
    await db.flush()
