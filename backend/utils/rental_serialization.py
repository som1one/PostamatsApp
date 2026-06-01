from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_location import LockerLocation
from backend.models.payment import Payment
from backend.models.product import Product
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.enums import PaymentStatus, PaymentType
from backend.models.product_filter import ProductFilter
from backend.models.reservation import Reservation
from backend.utils.return_requests import get_active_return_request_for_rental, serialize_return_request_payload
from backend.utils.lockers_utils import price_plan_to_minor_units
from backend.utils.products_utils import load_media_files_by_ids, public_media_url
from backend.utils.product_filters import resolve_effective_cover_url


async def _load_product_filter(db: AsyncSession, product: Product | None) -> ProductFilter | None:
    if product is None:
        return None
    return (
        await db.scalars(
            select(ProductFilter).where(ProductFilter.product_id == product.id).limit(1)
        )
    ).first()


async def serialize_rental_list_item(
    db: AsyncSession,
    rental: Rental,
    product: Product | None,
    locker: LockerLocation | None,
) -> dict:
    cover_url = None
    if product and product.cover_file_id:
        media_map = await load_media_files_by_ids(db, [product.cover_file_id])
        media = media_map.get(product.cover_file_id)
        if media is not None:
            cover_url = public_media_url(media.file_key)
    product_filter = await _load_product_filter(db, product)
    cover_url = resolve_effective_cover_url(cover_url, product_filter)

    pid = str(product.id) if product else ""
    pname = product.name if product else ""
    if product_filter and product_filter.name and product_filter.name.strip():
        pname = product_filter.name.strip()

    return {
        "id": str(rental.id),
        "status": rental.status.value,
        "cancelReason": rental.cancel_reason,
        "startsAt": rental.starts_at.isoformat() if rental.starts_at else None,
        "plannedEndAt": rental.planned_end_at.isoformat() if rental.planned_end_at else None,
        "actualEndAt": rental.actual_end_at.isoformat() if rental.actual_end_at else None,
        "product": {
            "id": pid,
            "name": pname,
            "coverUrl": cover_url,
        },
        "locker": {
            "id": str(locker.id) if locker else str(rental.pickup_locker_id),
            "name": locker.name if locker else None,
        },
    }


async def serialize_rental_detail(db: AsyncSession, rental: Rental) -> dict:
    unit = await db.get(InventoryUnit, rental.inventory_unit_id)
    product = await db.get(Product, unit.product_id) if unit and unit.product_id else None
    locker = await db.get(LockerLocation, rental.pickup_locker_id)

    cover_url = None
    if product and product.cover_file_id:
        media_map = await load_media_files_by_ids(db, [product.cover_file_id])
        media = media_map.get(product.cover_file_id)
        if media is not None:
            cover_url = public_media_url(media.file_key)
    product_filter = await _load_product_filter(db, product)
    cover_url = resolve_effective_cover_url(cover_url, product_filter)

    payment_summary = {
        "preauthAmount": 0,
        "capturedAmount": 0,
        "currency": "RUB",
    }
    if rental.reservation_id:
        pay_stmt = (
            select(Payment)
            .where(Payment.reservation_id == rental.reservation_id)
            .order_by(Payment.created_at.desc())
            .limit(5)
        )
        payments = (await db.scalars(pay_stmt)).all()
        for p in payments:
            if p.type == PaymentType.PREAUTH:
                payment_summary["preauthAmount"] = price_plan_to_minor_units(p.amount, p.currency)
                payment_summary["currency"] = p.currency
            if p.status == PaymentStatus.CAPTURED:
                payment_summary["capturedAmount"] = price_plan_to_minor_units(p.amount, p.currency)

    ev_stmt = (
        select(RentalEvent)
        .where(RentalEvent.rental_id == rental.id)
        .order_by(RentalEvent.created_at.asc())
    )
    events = (await db.scalars(ev_stmt)).all()
    events_out = [
        {
            "id": str(ev.id),
            "eventType": ev.event_type,
            "fromStatus": ev.from_status.value if ev.from_status else None,
            "toStatus": ev.to_status.value if ev.to_status else None,
            "source": ev.source.value,
            "createdAt": ev.created_at.isoformat(),
        }
        for ev in events
    ]

    res = await db.get(Reservation, rental.reservation_id) if rental.reservation_id else None
    active_return_request = await get_active_return_request_for_rental(db, rental.id)

    prod_payload = {
        "id": str(product.id) if product else "",
        "name": (
            product_filter.name.strip()
            if product_filter and product_filter.name and product_filter.name.strip()
            else product.name if product else ""
        ),
        "coverUrl": cover_url,
    }

    return {
        "rental": {
            "id": str(rental.id),
            "status": rental.status.value,
            "pickupPin": rental.pickup_pin,
            "startsAt": rental.starts_at.isoformat() if rental.starts_at else None,
            "plannedEndAt": rental.planned_end_at.isoformat() if rental.planned_end_at else None,
            "actualEndAt": rental.actual_end_at.isoformat() if rental.actual_end_at else None,
            "cellOpenedAt": rental.cell_opened_at.isoformat() if rental.cell_opened_at else None,
            "product": prod_payload,
            "pickupLocker": {
                "id": str(locker.id) if locker else str(rental.pickup_locker_id),
                "name": locker.name if locker else None,
                "address": locker.address if locker else None,
            },
            "paymentSummary": payment_summary,
            "events": events_out,
            "reservationId": str(res.id) if res else None,
            "returnRequest": (
                await serialize_return_request_payload(db, active_return_request)
                if active_return_request is not None
                else None
            ),
        }
    }
