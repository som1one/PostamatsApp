import hashlib
import hmac
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.enums import InventoryStatus, RentalEventSource, RentalStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent

logger = logging.getLogger(__name__)


def verify_esi_signature(body: bytes, signature_header: str | None) -> bool:
    secret = settings.ESI_WEBHOOK_SECRET
    if not secret:
        return True
    if not signature_header:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip())


async def _esi_event_seen(
    db: AsyncSession,
    rental_id: UUID,
    event_type_key: str,
    event_id: str,
) -> bool:
    stmt = select(RentalEvent).where(RentalEvent.rental_id == rental_id)
    rows = (await db.scalars(stmt)).all()
    for ev in rows:
        payload = ev.payload_json or {}
        if payload.get("eventId") == event_id and ev.event_type == event_type_key:
            return True
    return False


async def process_esi_webhook_payload(
    db: AsyncSession,
    *,
    event_type: str,
    event_id: str,
    rental_id: UUID | None,
) -> None:
    from fastapi import HTTPException

    if not rental_id:
        raise HTTPException(status_code=400, detail="INVALID_ESI_PAYLOAD")

    rental = await db.get(Rental, rental_id)
    if rental is None:
        raise HTTPException(status_code=404, detail="RENTAL_NOT_FOUND")

    now = datetime.now(timezone.utc)

    if event_type == "pickup_cell_opened":
        key = "pickup_cell_opened"
        if await _esi_event_seen(db, rental.id, key, event_id):
            return
        if rental.status != RentalStatus.PICKUP_READY:
            raise HTTPException(status_code=409, detail="INVALID_RENTAL_STATUS")
        prev = rental.status
        rental.status = RentalStatus.ACTIVE
        rental.starts_at = now
        unit = await db.get(InventoryUnit, rental.inventory_unit_id)
        if unit is not None:
            unit.status = InventoryStatus.RENTED
        db.add(
            RentalEvent(
                rental_id=rental.id,
                event_type=key,
                from_status=prev,
                to_status=RentalStatus.ACTIVE,
                source=RentalEventSource.LOCKER_WEBHOOK,
                payload_json={"eventId": event_id, "eventType": event_type},
            )
        )
        await db.commit()
        return

    if event_type == "return_cell_closed":
        key = "return_cell_closed"
        if await _esi_event_seen(db, rental.id, key, event_id):
            return
        if rental.status != RentalStatus.RETURN_IN_PROGRESS:
            raise HTTPException(status_code=409, detail="INVALID_RENTAL_STATUS")
        prev = rental.status
        rental.status = RentalStatus.COMPLETED
        rental.actual_end_at = now
        rental.completed_at = now
        unit = await db.get(InventoryUnit, rental.inventory_unit_id)
        if unit is not None:
            unit.status = InventoryStatus.AVAILABLE
        db.add(
            RentalEvent(
                rental_id=rental.id,
                event_type=key,
                from_status=prev,
                to_status=RentalStatus.COMPLETED,
                source=RentalEventSource.LOCKER_WEBHOOK,
                payload_json={"eventId": event_id, "eventType": event_type},
            )
        )
        await db.commit()
        return

    logger.info("Ignored unknown ESI eventType=%s", event_type)
