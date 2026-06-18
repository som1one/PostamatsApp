import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.models.enums import LockerCellStatus, LockerStatus
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation

logger = logging.getLogger(__name__)

# How long to wait for the cell to actually report `open: true` after sending
# the open command, and how often to poll the machine snapshot.
ESI_OPEN_CONFIRM_TIMEOUT_SECONDS = 5.0
ESI_OPEN_CONFIRM_POLL_INTERVAL_SECONDS = 0.7


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
    headers: dict[str, str] = {}
    if settings.ESI_API_KEY:
        headers["X-Api-Key"] = settings.ESI_API_KEY
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
            "serial",
        )
        if external_id is None:
            continue

        name = _resolve_nested(item, "name", "title", "locationName") or f"Locker {external_id}"
        address = _resolve_nested(
            item,
            "address",
            "location.address",
            "location.fullAddress",
            "addressLine",
        ) or "Address unavailable"
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


def _external_serial(locker: LockerLocation) -> str | None:
    raw = (locker.external_locker_id or "").strip()
    return raw or None


def _locker_uses_real_esi(locker: LockerLocation) -> bool:
    """True только если постамат реально подключён к провайдеру ESI.

    Сидовые/manual постаматы (`provider != "esi"`) физически не существуют —
    вызовы команд на ESI всё равно вернут 404. Их обрабатываем локально
    как при ESI_DEV_STUB: только обновляем БД, без сетевых вызовов.
    """
    provider = (locker.external_provider or "").strip().lower()
    return provider == "esi"


def _should_use_stub(locker: LockerLocation) -> bool:
    """Stub-режим включён глобально или конкретный постамат не на ESI."""
    if settings.ESI_DEV_STUB:
        return True
    if not _locker_uses_real_esi(locker):
        # Не-ESI постамат на не-stub окружении — это редкий легитимный кейс
        # (демо-постамат на проде), но он же типичный footgun: оператор завёл
        # боевой постамат и забыл указать `external_provider="esi"`. Логируем,
        # чтобы такие случаи были заметны в логах, а не "тихо успешными".
        logger.warning(
            "ESI command falls back to stub: locker_id=%s name=%r external_provider=%r",
            locker.id,
            locker.name,
            locker.external_provider,
        )
        return True
    return False


def _external_cell_key(cell: LockerCell) -> str | None:
    raw = (cell.external_cell_id or "").strip()
    return raw or None


def _cell_status_from_esi_state(state: str | None) -> LockerCellStatus | None:
    normalized = (state or "").strip().lower()
    # Поддерживаем и провайдерские, и наши внутренние имена — на случай
    # вызова из dev-stub, где состояние записывается напрямую.
    if normalized in ("vacant", "unassigned"):
        return LockerCellStatus.VACANT
    if normalized in ("occupied", "assigned"):
        return LockerCellStatus.OCCUPIED
    if normalized == "blocked":
        return LockerCellStatus.FAULT
    return None


def _esi_state_payload(state: str | None) -> str:
    """Переводит наш внутренний state в значение, ожидаемое ESI API.

    Провайдер принимает `vacant | occupied | blocked`.
    """
    normalized = (state or "").strip().lower()
    if normalized in ("vacant", "unassigned", ""):
        return "vacant"
    if normalized in ("occupied", "assigned"):
        return "occupied"
    if normalized == "blocked":
        return "blocked"
    return normalized


async def _load_provider_cell(
    db: AsyncSession,
    *,
    locker_id: UUID,
    cell_id: UUID,
) -> tuple[LockerLocation, LockerCell]:
    locker = await db.get(LockerLocation, locker_id)
    cell = await db.get(LockerCell, cell_id)
    if locker is None or cell is None or cell.locker_id != locker_id:
        raise EsiOpenError("CELL_NOT_FOUND")

    serial = _external_serial(locker)
    external_cell_id = _external_cell_key(cell)
    if not serial or not external_cell_id:
        raise EsiOpenError("ESI_NOT_CONFIGURED")
    return locker, cell


async def _esi_post(path: str, *, payload: dict | None = None, timeout: float | None = None) -> dict | None:
    if not settings.ESI_BASE_URL:
        raise EsiOpenError("ESI_NOT_CONFIGURED")

    try:
        async with httpx.AsyncClient(timeout=timeout or settings.ESI_RESERVE_TIMEOUT) as client:
            response = await client.post(
                f"{settings.ESI_BASE_URL}{path}",
                json=payload,
                headers=_get_esi_headers(),
            )
    except httpx.RequestError as exc:
        logger.exception("ESI POST failed for %s", path)
        raise EsiOpenError("ESI_HTTP_ERROR") from exc

    if response.status_code == 503:
        body_text = (response.text or "").lower()
        if "offline" in body_text:
            raise EsiOpenError("ESI_MACHINE_OFFLINE")

    if response.status_code == 404:
        # ESI вернул 404 на команду: либо serial машины неизвестен
        # провайдеру, либо у неё нет ячейки с таким external_cell_id.
        # Это конфигурационный рассинхрон (наши id не совпадают с ESI),
        # а не «постамат отклонил команду». Выносим отдельным кодом,
        # чтобы оператор видел понятную причину и не считал, что
        # сломалось железо.
        logger.warning(
            "ESI POST %s -> 404 (unknown machine serial or cell id): %s",
            path,
            response.text,
        )
        raise EsiOpenError("ESI_CELL_OR_MACHINE_NOT_FOUND")

    if response.status_code >= 400:
        logger.warning("ESI POST %s failed: %s %s", path, response.status_code, response.text)
        raise EsiOpenError("ESI_OPEN_FAILED")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


async def _esi_get(path: str, *, timeout: float | None = None) -> dict | list | None:
    if not settings.ESI_BASE_URL:
        raise EsiDiscoveryError("ESI_DISCOVERY_FAILED")

    try:
        async with httpx.AsyncClient(timeout=timeout or settings.ESI_SNAPSHOT_TIMEOUT) as client:
            response = await client.get(
                f"{settings.ESI_BASE_URL}{path}",
                headers=_get_esi_headers(),
            )
    except httpx.RequestError as exc:
        logger.exception("ESI GET failed for %s", path)
        raise EsiDiscoveryError("ESI_DISCOVERY_HTTP_ERROR") from exc

    if response.status_code >= 400:
        logger.warning("ESI GET %s failed: %s %s", path, response.status_code, response.text)
        raise EsiDiscoveryError("ESI_DISCOVERY_FAILED")
    if not response.content:
        return None
    return response.json()


async def sync_cell_state(
    db: AsyncSession,
    *,
    locker_id: UUID,
    cell_id: UUID,
    state: str,
    pin: str | None,
) -> None:
    locker = await db.get(LockerLocation, locker_id)
    cell = await db.get(LockerCell, cell_id)
    if locker is None or cell is None or cell.locker_id != locker_id:
        raise EsiOpenError("CELL_NOT_FOUND")

    if _should_use_stub(locker):
        mapped_status = _cell_status_from_esi_state(state)
        if mapped_status is not None:
            cell.status = mapped_status
        await db.flush()
        return

    serial = _external_serial(locker)
    external_cell_id = _external_cell_key(cell)
    if not serial or not external_cell_id:
        raise EsiOpenError("ESI_NOT_CONFIGURED")

    esi_state = _esi_state_payload(state)
    # ESI отвергает запрос с непустым `pin`, если ячейка переводится
    # в `vacant` (свободную). Поэтому при освобождении принудительно
    # стираем pin, что бы ни пришло сверху.
    esi_pin = "" if esi_state == "vacant" else (pin or "0000")
    await _esi_post(
        f"/set-cell/{serial}/{external_cell_id}",
        payload={"state": esi_state, "pin": esi_pin},
    )


async def fetch_machine_snapshot(serial: str) -> dict | None:
    if settings.ESI_DEV_STUB:
        return None
    payload = await _esi_get(f"/machine/{serial}")
    return payload if isinstance(payload, dict) else None


async def is_machine_online(serial: str) -> bool | None:
    """Возвращает True/False по полю online из снапшота. Возвращает None,
    если ESI не знает такой serial (404) — это «не сконфигурирован», а не
    офлайн. Не бросает исключений: используется для pre-check перед
    отправкой команды.
    """
    if settings.ESI_DEV_STUB:
        return True
    try:
        snapshot = await fetch_machine_snapshot(serial)
    except EsiDiscoveryError:
        return None
    if not isinstance(snapshot, dict):
        return None
    # Игнорируем флаг 'online' в снапшоте ESI, так как он может быть недостоверным.
    # Если ESI возвращает корректный снапшот, считаем постамат онлайн.
    return True


async def fetch_machines_snapshot() -> list[dict]:
    if settings.ESI_DEV_STUB:
        return []
    payload = await _esi_get("/machines")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if "items" in payload and isinstance(payload["items"], list):
            return [item for item in payload["items"] if isinstance(item, dict)]
        if "machines" in payload and isinstance(payload["machines"], list):
            return [item for item in payload["machines"] if isinstance(item, dict)]
        # Some providers key by serial.
        machines: list[dict] = []
        for key, value in payload.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("serial", key)
                machines.append(item)
        return machines
    return []


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
        ((provider or "").strip().lower(), external_id.strip())
        for provider, external_id in existing_rows
        if external_id
    }

    if settings.ESI_DEV_STUB or not settings.ESI_BASE_URL:
        stub_city = city_name or "Unknown city"
        stub_items = [
            {
                "id": f"stub-{stub_city.lower().replace(' ', '-')}-001",
                "name": f"{stub_city} Center",
                "address": f"{stub_city}, Central street, 1",
                "cityName": stub_city,
                "latitude": 53.9,
                "longitude": 27.56,
                "provider": "esi",
            },
            {
                "id": f"stub-{stub_city.lower().replace(' ', '-')}-002",
                "name": f"{stub_city} East",
                "address": f"{stub_city}, East street, 14",
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

    raw_items: list[dict] = []

    try:
        machines = await fetch_machines_snapshot()
        if machines:
            raw_items.extend(machines)
    except EsiDiscoveryError:
        logger.info("ESI /machines discovery unavailable, falling back to legacy endpoints")

    if not raw_items:
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
                [{"city": city_name}, {"cityName": city_name}, {"q": city_name}]
            )
        query_candidates.append(None)

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
                        if raw_items:
                            break
                    if raw_items:
                        break
        except EsiDiscoveryError:
            raise

        if not raw_items:
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
    cell_id: UUID,
    pickup_pin: str,
) -> None:
    locker = await db.get(LockerLocation, locker_id)
    cell = await db.get(LockerCell, cell_id)
    if locker is None or cell is None or cell.locker_id != locker_id:
        raise EsiReserveError("LOCKER_CELL_MISMATCH")

    if cell.status in (LockerCellStatus.FAULT, LockerCellStatus.DISABLED):
        raise EsiReserveError("CELL_NOT_RESERVABLE")

    # Pre-check: если постамат сейчас оффлайн или ESI ничего о нём не знает,
    # не пытаемся писать команду (всё равно потеряется или будет 503).
    # Сидовые/manual постаматы пропускаем: для них sync_cell_state всё
    # сделает локально по веткам _should_use_stub.
    if not _should_use_stub(locker):
        serial = _external_serial(locker)
        if not serial:
            raise EsiReserveError("ESI_NOT_CONFIGURED")
        online = await is_machine_online(serial)
        if online is None:
            # ESI не знает такой serial — постамат не привязан к API.
            raise EsiReserveError("ESI_NOT_CONFIGURED")
        if not online:
            raise EsiReserveError("ESI_MACHINE_OFFLINE")

    try:
        await sync_cell_state(
            db,
            locker_id=locker_id,
            cell_id=cell_id,
            state="occupied",
            pin=pickup_pin,
        )
    except EsiOpenError as exc:
        code = str(exc)
        if code == "ESI_NOT_CONFIGURED":
            raise EsiReserveError("ESI_NOT_CONFIGURED") from exc
        if code == "ESI_MACHINE_OFFLINE":
            raise EsiReserveError("ESI_MACHINE_OFFLINE") from exc
        if code == "ESI_HTTP_ERROR":
            raise EsiReserveError("ESI_HTTP_ERROR") from exc
        raise EsiReserveError("ESI_RESERVE_FAILED") from exc

    cell.status = LockerCellStatus.RESERVED
    await db.flush()


async def _wait_for_cell_open(
    serial: str,
    external_cell_id: str,
    *,
    timeout_seconds: float = ESI_OPEN_CONFIRM_TIMEOUT_SECONDS,
    poll_interval_seconds: float = ESI_OPEN_CONFIRM_POLL_INTERVAL_SECONDS,
) -> bool:
    """Polls the machine snapshot until the cell reports `open: true`.

    Returns True if the cell opened within `timeout_seconds`, False otherwise.
    Snapshot fetch errors are treated as "not yet open" and the loop keeps
    polling until timeout — so a single transient ESI hiccup doesn't
    prematurely fail an open that's actually working.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while True:
        try:
            snapshot = await fetch_machine_snapshot(serial)
        except EsiDiscoveryError:
            snapshot = None

        if isinstance(snapshot, dict):
            cells = snapshot.get("cells")
            if isinstance(cells, dict):
                cell_payload = cells.get(str(external_cell_id))
                if isinstance(cell_payload, dict) and bool(cell_payload.get("open")):
                    return True

        if asyncio.get_event_loop().time() >= deadline:
            return False
        await asyncio.sleep(poll_interval_seconds)


async def admin_trigger_open_cell(
    db: AsyncSession,
    *,
    locker_id: UUID,
    cell_id: UUID,
) -> None:
    locker = await db.get(LockerLocation, locker_id)
    cell = await db.get(LockerCell, cell_id)
    if cell is None or locker is None or cell.locker_id != locker_id:
        raise EsiOpenError("CELL_NOT_FOUND")

    if cell.status in (LockerCellStatus.FAULT, LockerCellStatus.DISABLED):
        raise EsiOpenError("CELL_NOT_OPERABLE")

    now = datetime.now(timezone.utc)

    if _should_use_stub(locker):
        cell.status = LockerCellStatus.OPENED
        cell.last_opened_at = now
        cell.last_event_at = now
        await db.flush()
        return

    serial = _external_serial(locker)
    external_cell_id = _external_cell_key(cell)
    if not serial or not external_cell_id:
        raise EsiOpenError("ESI_NOT_CONFIGURED")

    # Pre-check: не пытаемся открывать ячейку, если постамат офлайн или
    # serial не зарегистрирован в ESI.
    online = await is_machine_online(serial)
    if online is None:
        raise EsiOpenError("ESI_NOT_CONFIGURED")
    if not online:
        raise EsiOpenError("ESI_MACHINE_OFFLINE")

    await _esi_post(f"/open-cell/{serial}/{external_cell_id}")

    # ESI 200 для /open-cell означает только "команда поставлена в очередь".
    # Чтобы не врать пользователю, дожидаемся подтверждения через снапшот:
    # cells[id].open должен стать true. Если за таймаут не подтвердилось —
    # бросаем ошибку, статус rental не двигаем.
    confirmed = await _wait_for_cell_open(serial, external_cell_id)
    if not confirmed:
        logger.warning(
            "ESI open-cell not confirmed within timeout: serial=%s cell=%s",
            serial,
            external_cell_id,
        )
        raise EsiOpenError("ESI_OPEN_NOT_CONFIRMED")

    cell.status = LockerCellStatus.OPENED
    cell.last_opened_at = now
    cell.last_event_at = now
    await db.flush()


async def esi_trigger_return_cell_open(
    db: AsyncSession,
    *,
    locker_id: UUID,
    cell_id: UUID,
    rental_id: UUID,
    pin: str,
) -> None:
    locker = await db.get(LockerLocation, locker_id)
    cell = await db.get(LockerCell, cell_id)
    if cell is None or locker is None or cell.locker_id != locker_id:
        raise EsiReturnOpenError("RETURN_CELL_NOT_FOUND")

    if cell.status in (LockerCellStatus.FAULT, LockerCellStatus.DISABLED):
        raise EsiReturnOpenError("RETURN_CELL_NOT_OPERABLE")

    now = datetime.now(timezone.utc)

    if _should_use_stub(locker):
        cell.status = LockerCellStatus.OPENED
        cell.last_opened_at = now
        cell.last_event_at = now
        await db.flush()
        return

    serial = _external_serial(locker)
    external_cell_id = _external_cell_key(cell)
    if not serial or not external_cell_id:
        raise EsiReturnOpenError("ESI_NOT_CONFIGURED")

    try:
        # Бронируем ячейку под возврат: ESI ожидает `occupied` + pin
        # (`vacant` с непустым pin провайдер не принимает). После этого
        # принудительно открываем дверцу — клиент кладёт товар.
        await _esi_post(
            f"/set-cell/{serial}/{external_cell_id}",
            payload={"state": _esi_state_payload("occupied"), "pin": pin},
        )
        await _esi_post(f"/open-cell/{serial}/{external_cell_id}")
    except EsiOpenError as exc:
        code = str(exc)
        if code == "ESI_NOT_CONFIGURED":
            raise EsiReturnOpenError("ESI_NOT_CONFIGURED") from exc
        if code == "ESI_HTTP_ERROR":
            raise EsiReturnOpenError("ESI_HTTP_ERROR") from exc
        raise EsiReturnOpenError("ESI_OPEN_FAILED") from exc

    confirmed = await _wait_for_cell_open(serial, external_cell_id)
    if not confirmed:
        logger.warning(
            "ESI return open-cell not confirmed within timeout: serial=%s cell=%s rental=%s",
            serial,
            external_cell_id,
            rental_id,
        )
        raise EsiReturnOpenError("ESI_OPEN_NOT_CONFIRMED")

    cell.status = LockerCellStatus.OPENED
    cell.last_opened_at = now
    cell.last_event_at = now
    await db.flush()
