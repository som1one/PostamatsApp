import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.enums import LockerCellStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation

logger = logging.getLogger(__name__)


class EsiReserveError(Exception):
    pass


class EsiOpenError(Exception):
    pass


class EsiReturnOpenError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class EsiDiscoveryError(Exception):
    pass


def _get_esi_headers() -> dict[str, str]:
    headers = {}
    if settings.ESI_API_KEY:
        headers["Authorization"] = f"Bearer {settings.ESI_API_KEY}"
    return headers


def _resolve_nested(payload: dict, *paths: str):
    for path in paths:
        value = payload
        for part in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value not in (None, ""):
            return value
    return None


def _as_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_external_lockers(raw_items: list[dict], city_name: str | None) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    normalized: list[dict] = []
    city_filter = city_name.strip().lower() if city_name else None

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        external_id = _resolve_nested(
            item,
            "lockerId",
            "id",
            "externalLockerId",
            "locationId",
            "code",
        )
        if external_id is None:
            continue

        name = _resolve_nested(item, "name", "title", "locationName") or f"Постамат {external_id}"
        address = _resolve_nested(
            item,
            "address",
            "location.address",
            "location.fullAddress",
            "addressLine",
        ) or "Адрес не указан"
        item_city = _resolve_nested(item, "city", "cityName", "location.city")

        if city_filter and item_city:
            if city_filter not in str(item_city).strip().lower():
                continue

        provider = (
            _resolve_nested(item, "provider", "providerCode", "externalProvider")
            or "esi"
        )
        key = (str(provider).strip().lower(), str(external_id).strip())
        if key in seen:
            continue
        seen.add(key)

        normalized.append(
            {
                "externalLockerId": str(external_id).strip(),
                "provider": str(provider).strip().lower(),
                "name": str(name).strip(),
                "address": str(address).strip(),
                "cityName": str(item_city).strip() if item_city else city_name,
                "lat": _as_float(_resolve_nested(item, "lat", "latitude", "location.lat")),
                "lon": _as_float(_resolve_nested(item, "lon", "longitude", "location.lon")),
                "workingHours": _resolve_nested(item, "workingHours", "openingHours", "schedule"),
                "raw": item,
            }
        )

    return normalized


async def discover_external_lockers(
    db: AsyncSession,
    *,
    city_name: str | None,
) -> list[dict]:
    existing_rows = (
        await db.execute(
            select(
                LockerLocation.external_provider,
                LockerLocation.external_locker_id,
            ).where(LockerLocation.external_locker_id.is_not(None))
        )
    ).all()
    existing_keys = {
        (
            (provider or "").strip().lower(),
            external_id.strip(),
        )
        for provider, external_id in existing_rows
        if external_id
    }

    if settings.ESI_DEV_STUB or not settings.ESI_BASE_URL:
        stub_city = city_name or "Без города"
        stub_items = [
            {
                "id": f"stub-{stub_city.lower().replace(' ', '-')}-001",
                "name": f"{stub_city} Центр",
                "address": f"{stub_city}, Центральная улица, 1",
                "cityName": stub_city,
                "latitude": 53.9,
                "longitude": 27.56,
                "provider": "esi",
            },
            {
                "id": f"stub-{stub_city.lower().replace(' ', '-')}-002",
                "name": f"{stub_city} Восток",
                "address": f"{stub_city}, Восточная улица, 14",
                "cityName": stub_city,
                "latitude": 53.91,
                "longitude": 27.59,
                "provider": "esi",
            },
        ]
        normalized = _normalize_external_lockers(stub_items, city_name)
        return [
            item
            for item in normalized
            if (item["provider"], item["externalLockerId"]) not in existing_keys
        ]

    endpoints = [
        "/lockers",
        "/locations",
        "/postamats",
        "/v1/lockers",
        "/v1/locations",
    ]
    query_candidates = []
    if city_name:
        query_candidates.extend(
            [
                {"city": city_name},
                {"cityName": city_name},
                {"q": city_name},
            ]
        )
    query_candidates.append(None)

    raw_items: list[dict] | None = None
    last_error: str | None = None

    try:
        async with httpx.AsyncClient(timeout=settings.ESI_DISCOVERY_TIMEOUT) as client:
            for endpoint in endpoints:
                for params in query_candidates:
                    try:
                        response = await client.get(
                            f"{settings.ESI_BASE_URL}{endpoint}",
                            params=params,
                            headers=_get_esi_headers(),
                        )
                    except httpx.RequestError as exc:
                        logger.exception("ESI discovery request failed")
                        raise EsiDiscoveryError("ESI_DISCOVERY_HTTP_ERROR") from exc

                    if response.status_code == 404:
                        continue
                    if response.status_code >= 400:
                        last_error = response.text
                        continue

                    payload = response.json()
                    if isinstance(payload, list):
                        raw_items = payload
                    elif isinstance(payload, dict):
                        for key in ("items", "lockers", "locations", "results", "data"):
                            candidate = payload.get(key)
                            if isinstance(candidate, list):
                                raw_items = candidate
                                break
                    if raw_items is not None:
                        break
                if raw_items is not None:
                    break
    except EsiDiscoveryError:
        raise

    if raw_items is None:
        if last_error:
            logger.warning("ESI discovery failed: %s", last_error)
        raise EsiDiscoveryError("ESI_DISCOVERY_FAILED")

    normalized = _normalize_external_lockers(raw_items, city_name)
    return [
        item
        for item in normalized
        if (item["provider"], item["externalLockerId"]) not in existing_keys
    ]


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
    headers = _get_esi_headers()

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


async def admin_trigger_open_cell(
    db: AsyncSession,
    *,
    locker_id: UUID,
    cell_id: UUID,
) -> None:
    cell = await db.get(LockerCell, cell_id)
    if cell is None or cell.locker_id != locker_id:
        raise EsiOpenError("CELL_NOT_FOUND")

    if cell.status in (LockerCellStatus.FAULT, LockerCellStatus.DISABLED):
        raise EsiOpenError("CELL_NOT_OPERABLE")

    now = datetime.now(timezone.utc)

    if settings.ESI_DEV_STUB:
        cell.last_opened_at = now
        cell.last_event_at = now
        await db.flush()
        return

    if not settings.ESI_BASE_URL:
        raise EsiOpenError("ESI_NOT_CONFIGURED")

    url = f"{settings.ESI_BASE_URL}/cells/open"
    headers = _get_esi_headers()

    payload = {
        "lockerId": str(locker_id),
        "cellId": str(cell.id),
        "externalCellId": cell.external_cell_id,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.ESI_RESERVE_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        logger.exception("ESI open-cell HTTP error")
        raise EsiOpenError("ESI_HTTP_ERROR") from exc

    if resp.status_code >= 400:
        logger.warning("ESI open-cell failed: %s %s", resp.status_code, resp.text)
        raise EsiOpenError("ESI_OPEN_FAILED")

    cell.last_opened_at = now
    cell.last_event_at = now
    await db.flush()


async def esi_trigger_return_cell_open(
    db: AsyncSession,
    *,
    locker_id: UUID,
    cell_id: UUID,
    rental_id: UUID,
) -> None:
    cell = await db.get(LockerCell, cell_id)
    if cell is None or cell.locker_id != locker_id:
        raise EsiReturnOpenError("RETURN_CELL_NOT_FOUND")

    if cell.status in (LockerCellStatus.FAULT, LockerCellStatus.DISABLED):
        raise EsiReturnOpenError("RETURN_CELL_NOT_OPERABLE")

    now = datetime.now(timezone.utc)

    if settings.ESI_DEV_STUB:
        cell.last_opened_at = now
        cell.last_event_at = now
        await db.flush()
        return

    if not settings.ESI_BASE_URL:
        raise EsiReturnOpenError("ESI_NOT_CONFIGURED")

    url = f"{settings.ESI_BASE_URL}/cells/return-open"
    headers = _get_esi_headers()
    payload = {
        "lockerId": str(locker_id),
        "cellId": str(cell.id),
        "externalCellId": cell.external_cell_id,
        "rentalId": str(rental_id),
    }

    try:
        async with httpx.AsyncClient(timeout=settings.ESI_RESERVE_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        logger.exception("ESI return-open HTTP error")
        raise EsiReturnOpenError("ESI_HTTP_ERROR") from exc

    if resp.status_code >= 400:
        logger.warning("ESI return-open failed: %s %s", resp.status_code, resp.text)
        raise EsiReturnOpenError("ESI_OPEN_FAILED")

    cell.last_opened_at = now
    cell.last_event_at = now
    await db.flush()
