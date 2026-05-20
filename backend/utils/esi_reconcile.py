import asyncio
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.core.settings import settings
from backend.models.enums import LockerCellStatus, LockerStatus, RentalEventSource, ReturnRequestStatus
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.return_request import ReturnRequest
from backend.utils.esi_client import fetch_machine_snapshot, fetch_machines_snapshot
from backend.utils.reservation_utils import ensure_utc
from backend.utils.return_requests import complete_return_request, fail_return_request

logger = logging.getLogger(__name__)


def _snapshot_cells(snapshot: dict) -> dict[str, dict]:
    cells = snapshot.get("cells")
    if isinstance(cells, dict):
        return {
            str(key): value
            for key, value in cells.items()
            if isinstance(value, dict)
        }
    return {}


def _state_to_cell_status(state: str | None, open_flag: bool) -> LockerCellStatus | None:
    if open_flag:
        return LockerCellStatus.OPENED
    normalized = (state or "").strip().lower()
    if normalized == "vacant":
        return LockerCellStatus.VACANT
    if normalized == "occupied":
        return LockerCellStatus.OCCUPIED
    if normalized == "blocked":
        return LockerCellStatus.FAULT
    return None


async def reconcile_esi_and_returns() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        active_requests_stmt = select(ReturnRequest).where(
            ReturnRequest.status.in_(
                (
                    ReturnRequestStatus.CREATED,
                    ReturnRequestStatus.LOCKER_OPENED,
                    ReturnRequestStatus.AWAITING_CLOSE,
                )
            )
        )
        active_requests = list((await db.scalars(active_requests_stmt)).all())

        for request in active_requests:
            if ensure_utc(request.deadline_at) <= now:
                await fail_return_request(
                    db,
                    request=request,
                    reason="return_timeout",
                    source=RentalEventSource.SYSTEM,
                )

        # Берём только постаматы реального ESI-провайдера. Сидовые/тестовые
        # точки (`seed`, `manual` и т.п.) не зарегистрированы у ESI, и для
        # них `GET /machine/{serial}` будет всегда отвечать 404 — это шумит
        # в логах и впустую тратит таймауты.
        lockers_stmt = select(LockerLocation).where(
            LockerLocation.external_locker_id.is_not(None),
            LockerLocation.external_provider == "esi",
        )
        lockers = list((await db.scalars(lockers_stmt)).all())
        if not lockers:
            await db.commit()
            return

        snapshots_by_serial: dict[str, dict] = {}
        if not settings.ESI_DEV_STUB and settings.ESI_BASE_URL:
            try:
                for snapshot in await fetch_machines_snapshot():
                    serial = str(snapshot.get("serial") or snapshot.get("id") or "").strip()
                    if serial:
                        snapshots_by_serial[serial] = snapshot
            except Exception:
                logger.exception("Failed to fetch ESI machine snapshots")

        for locker in lockers:
            serial = (locker.external_locker_id or "").strip()
            if not serial:
                continue

            snapshot = snapshots_by_serial.get(serial)
            if snapshot is None and not settings.ESI_DEV_STUB and settings.ESI_BASE_URL:
                try:
                    snapshot = await fetch_machine_snapshot(serial)
                except Exception:
                    logger.exception("Failed to fetch ESI machine snapshot for %s", serial)
                    snapshot = None

            if snapshot is None:
                continue

            locker.last_online_at = now
            locker.status = LockerStatus.ONLINE if snapshot.get("online", True) else LockerStatus.OFFLINE

            cells_by_external = {}
            locker_cells = (
                await db.scalars(select(LockerCell).where(LockerCell.locker_id == locker.id))
            ).all()
            for cell in locker_cells:
                if cell.external_cell_id:
                    cells_by_external[cell.external_cell_id] = cell

            for external_cell_id, cell_snapshot in _snapshot_cells(snapshot).items():
                cell = cells_by_external.get(external_cell_id)
                if cell is None:
                    continue
                open_flag = bool(cell_snapshot.get("open"))
                mapped_status = _state_to_cell_status(cell_snapshot.get("state"), open_flag)
                if mapped_status is not None:
                    cell.status = mapped_status
                cell.last_event_at = now
                if open_flag:
                    cell.last_opened_at = now
                else:
                    cell.last_closed_at = now

        if not settings.ESI_DEV_STUB and settings.ESI_BASE_URL:
            active_requests = list((await db.scalars(active_requests_stmt)).all())
            for request in active_requests:
                if request.status not in (
                    ReturnRequestStatus.CREATED,
                    ReturnRequestStatus.LOCKER_OPENED,
                    ReturnRequestStatus.AWAITING_CLOSE,
                ):
                    continue
                locker = await db.get(LockerLocation, request.locker_id)
                cell = await db.get(LockerCell, request.cell_id)
                if locker is None or cell is None or not locker.external_locker_id or not cell.external_cell_id:
                    continue
                snapshot = snapshots_by_serial.get(locker.external_locker_id)
                if snapshot is None:
                    continue
                cell_snapshot = _snapshot_cells(snapshot).get(cell.external_cell_id)
                if not cell_snapshot:
                    continue
                is_open = bool(cell_snapshot.get("open"))
                state = str(cell_snapshot.get("state") or "").strip().lower()
                if not is_open and state == "occupied":
                    await complete_return_request(
                        db,
                        request=request,
                        provider_event_id=f"reconcile:{request.id}:{int(now.timestamp())}",
                        source=RentalEventSource.SYSTEM,
                    )

        await db.commit()


def esi_reconcile_worker(
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    interval = max(10, int(settings.ESI_RECONCILE_INTERVAL_SECONDS))
    try:
        asyncio.run_coroutine_threadsafe(reconcile_esi_and_returns(), loop).result()
        while not stop_event.wait(interval):
            asyncio.run_coroutine_threadsafe(reconcile_esi_and_returns(), loop).result()
    except Exception:
        logger.exception("ESI reconcile scheduler stopped unexpectedly")


def start_esi_reconcile_scheduler(
    loop: asyncio.AbstractEventLoop,
) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    worker = threading.Thread(
        target=esi_reconcile_worker,
        args=(loop, stop_event),
        name="esi-reconcile-scheduler",
        daemon=True,
    )
    worker.start()
    return worker, stop_event


async def stop_esi_reconcile_scheduler(
    worker: threading.Thread | None,
    stop_event: threading.Event | None,
) -> None:
    if worker is None or stop_event is None:
        return
    stop_event.set()
    await asyncio.to_thread(worker.join, 5)
