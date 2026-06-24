import hashlib
import hmac
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.esi_event_log import EsiEventLog
from backend.models.enums import (
    InventoryStatus,
    LockerCellStatus,
    LockerStatus,
    RentalEventSource,
    RentalStatus,
    ReturnRequestStatus,
)
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.product import Product
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.return_request import ReturnRequest
from backend.utils.inventory_confirmation_notifications import (
    notify_inventory_awaiting_confirmation,
)
from backend.utils.inventory_tracking import add_inventory_movement
from backend.utils.return_requests import (
    complete_return_request,
    get_active_return_request_by_cell,
    get_active_return_request_for_rental,
)

logger = logging.getLogger(__name__)

OPEN_EVENTS = frozenset({"pickup_cell_opened", "cell_open", "cell_opened"})
CLOSE_EVENTS = frozenset({"pickup_cell_closed", "return_cell_closed", "cell_close", "cell_closed"})
VACANT_EVENTS = frozenset({"pickup_complete", "cell_vacant", "vacant"})
OCCUPIED_EVENTS = frozenset({"return_cell_closed", "cell_occupied", "occupied"})


def verify_esi_signature(body: bytes, signature_header: str | None) -> bool:
    secret = settings.ESI_WEBHOOK_SECRET
    if not secret:
        return True
    if not signature_header:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip())


def normalize_event_type(raw: str) -> str:
    return raw.strip().lower().replace("-", "_").replace(" ", "_")


def _parse_optional_uuid(value) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value).strip())
    except (TypeError, ValueError):
        return None


def _extract_locker_external_id(payload: dict) -> str | None:
    for key in ("lockerExternalId", "serial", "machineSerial", "lockerId"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _extract_cell_external_id(payload: dict) -> str | None:
    for key in ("cellExternalId", "cellId"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


async def _find_locker(
    db: AsyncSession,
    locker_external_id: str | None,
) -> LockerLocation | None:
    locker_uuid = _parse_optional_uuid(locker_external_id)
    if locker_uuid is not None:
        locker = await db.get(LockerLocation, locker_uuid)
        if locker is not None:
            return locker

    if locker_external_id:
        stmt = select(LockerLocation).where(LockerLocation.external_locker_id == locker_external_id).limit(1)
        return (await db.scalars(stmt)).first()
    return None


async def _find_cell(
    db: AsyncSession,
    *,
    locker: LockerLocation | None,
    cell_external_id: str | None,
) -> LockerCell | None:
    cell_uuid = _parse_optional_uuid(cell_external_id)
    if cell_uuid is not None:
        cell = await db.get(LockerCell, cell_uuid)
        if cell is not None and (locker is None or cell.locker_id == locker.id):
            return cell

    if locker is not None and cell_external_id:
        stmt = (
            select(LockerCell)
            .where(
                LockerCell.locker_id == locker.id,
                LockerCell.external_cell_id == cell_external_id,
            )
            .limit(1)
        )
        return (await db.scalars(stmt)).first()
    return None


async def _mark_pickup_opened(
    db: AsyncSession,
    *,
    rental: Rental,
    cell: LockerCell | None,
    event_id: str,
    event_type: str,
    now: datetime,
) -> str:
    if rental.status != RentalStatus.PICKUP_READY:
        return "ignored_pickup_open_status"

    prev = rental.status
    rental.status = RentalStatus.PICKUP_OPENED
    if cell is not None:
        cell.status = LockerCellStatus.OPENED
        cell.last_opened_at = now
        cell.last_event_at = now
    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type="pickup_cell_opened",
            from_status=prev,
            to_status=RentalStatus.PICKUP_OPENED,
            source=RentalEventSource.LOCKER_WEBHOOK,
            payload_json={"eventId": event_id, "eventType": event_type},
        )
    )
    return "pickup_opened"


async def _mark_pickup_completed(
    db: AsyncSession,
    *,
    rental: Rental,
    cell: LockerCell | None,
    unit: InventoryUnit | None,
    event_id: str,
    event_type: str,
    now: datetime,
) -> str:
    if rental.status not in (RentalStatus.PICKUP_READY, RentalStatus.PICKUP_OPENED):
        return "ignored_pickup_complete_status"

    prev_rental_status = rental.status
    prev_unit_status = unit.status if unit is not None else None
    prev_cell_id = unit.locker_cell_id if unit is not None else None

    rental.status = RentalStatus.ACTIVE
    rental.starts_at = rental.starts_at or now

    if unit is not None:
        unit.status = InventoryStatus.RENTED
        unit.locker_cell_id = None

    if cell is not None:
        cell.status = LockerCellStatus.VACANT
        cell.last_closed_at = now
        cell.last_event_at = now

    if unit is not None:
        add_inventory_movement(
            db,
            unit=unit,
            from_locker_id=rental.pickup_locker_id,
            to_locker_id=None,
            from_cell_id=prev_cell_id,
            to_cell_id=None,
            from_status=prev_unit_status,
            to_status=InventoryStatus.RENTED,
            reason="pickup_completed",
        )

    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type="pickup_completed",
            from_status=prev_rental_status,
            to_status=RentalStatus.ACTIVE,
            source=RentalEventSource.LOCKER_WEBHOOK,
            payload_json={"eventId": event_id, "eventType": event_type},
        )
    )
    return "pickup_completed"


async def _resolve_return_request(
    db: AsyncSession,
    *,
    rental: Rental | None,
    locker: LockerLocation | None,
    cell: LockerCell | None,
) -> ReturnRequest | None:
    request = None
    if rental is not None:
        request = await get_active_return_request_for_rental(db, rental.id)
        if request is not None:
            return request
    if locker is not None and cell is not None:
        return await get_active_return_request_by_cell(db, locker_id=locker.id, cell_id=cell.id)
    return None


async def process_esi_webhook_payload(
    db: AsyncSession,
    *,
    payload: dict,
) -> None:
    raw_event_type = str(payload.get("eventType") or "").strip()
    event_type = normalize_event_type(raw_event_type)
    event_id = str(payload.get("eventId") or "").strip()
    if not raw_event_type or not event_id:
        raise ValueError("INVALID_ESI_PAYLOAD")

    existing = (
        await db.scalars(select(EsiEventLog).where(EsiEventLog.provider_event_id == event_id).limit(1))
    ).first()
    if existing is not None:
        return

    now = datetime.now(timezone.utc)
    log = EsiEventLog(
        provider_event_id=event_id,
        event_type=event_type,
        locker_external_id=_extract_locker_external_id(payload),
        cell_external_id=_extract_cell_external_id(payload),
        payload_json=payload,
    )
    db.add(log)
    await db.flush()

    result = "ignored"
    rental: Rental | None = None
    unit: InventoryUnit | None = None
    notify_confirmation = False
    locker = await _find_locker(db, log.locker_external_id)
    cell = await _find_cell(db, locker=locker, cell_external_id=log.cell_external_id)

    rental_id = _parse_optional_uuid(payload.get("rentalId"))
    if rental_id is not None:
        rental = await db.get(Rental, rental_id)

    if rental is not None:
        unit = await db.get(InventoryUnit, rental.inventory_unit_id)
        if cell is None and unit is not None and unit.locker_cell_id is not None:
            candidate = await db.get(LockerCell, unit.locker_cell_id)
            if candidate is not None and (
                log.cell_external_id in (None, "", candidate.external_cell_id, str(candidate.id))
            ):
                cell = candidate
        if locker is None and cell is not None:
            locker = await db.get(LockerLocation, cell.locker_id)

    if cell is not None and event_type in OPEN_EVENTS:
        cell.status = LockerCellStatus.OPENED
        cell.last_opened_at = now
        cell.last_event_at = now
    elif cell is not None and event_type in OCCUPIED_EVENTS:
        # Ставим OCCUPIED только если в ячейке реально есть InventoryUnit
        # или есть связанный rental (возврат). Иначе — "фантомное" занятие,
        # которое блокирует возвраты для клиентов.
        has_unit = (
            await db.execute(
                select(InventoryUnit.id)
                .where(InventoryUnit.locker_cell_id == cell.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if has_unit is not None or rental is not None:
            cell.status = LockerCellStatus.OCCUPIED
        else:
            cell.status = LockerCellStatus.VACANT
        cell.last_closed_at = now
        cell.last_event_at = now
    elif cell is not None and event_type in VACANT_EVENTS:
        cell.status = LockerCellStatus.VACANT
        cell.last_closed_at = now
        cell.last_event_at = now
    elif cell is not None and event_type in CLOSE_EVENTS:
        cell.last_closed_at = now
        cell.last_event_at = now

    if locker is not None:
        locker.last_online_at = now
        if locker.status == LockerStatus.OFFLINE:
            locker.status = LockerStatus.ONLINE

    if rental is not None and event_type in OPEN_EVENTS and rental.status == RentalStatus.PICKUP_READY:
        result = await _mark_pickup_opened(
            db,
            rental=rental,
            cell=cell,
            event_id=event_id,
            event_type=raw_event_type,
            now=now,
        )
    elif rental is not None and event_type in (VACANT_EVENTS | CLOSE_EVENTS) and rental.status in (
        RentalStatus.PICKUP_READY,
        RentalStatus.PICKUP_OPENED,
    ):
        result = await _mark_pickup_completed(
            db,
            rental=rental,
            cell=cell,
            unit=unit,
            event_id=event_id,
            event_type=raw_event_type,
            now=now,
        )
    else:
        return_request = await _resolve_return_request(db, rental=rental, locker=locker, cell=cell)
        if return_request is not None and event_type in OCCUPIED_EVENTS | CLOSE_EVENTS:
            if return_request.status in (
                ReturnRequestStatus.CREATED,
                ReturnRequestStatus.LOCKER_OPENED,
                ReturnRequestStatus.AWAITING_CLOSE,
            ):
                rental, unit = await complete_return_request(
                    db,
                    request=return_request,
                    provider_event_id=event_id,
                    source=RentalEventSource.LOCKER_WEBHOOK,
                )
                log.matched_return_request_id = return_request.id
                result = "return_completed"
                notify_confirmation = rental is not None and unit is not None
        elif cell is not None:
            result = "unexpected_cell_event"

    if rental is not None:
        log.matched_rental_id = rental.id
    log.processing_result = result
    log.processed_at = now
    await db.commit()

    if notify_confirmation and rental is not None and unit is not None and locker is not None and cell is not None:
        product = await db.get(Product, unit.product_id)
        if product is not None:
            notify_inventory_awaiting_confirmation(
                product=product,
                locker=locker,
                cell=cell,
                unit=unit,
                rental=rental,
            )
