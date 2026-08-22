import asyncio
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.core.settings import settings
from backend.models.enums import (
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
from backend.utils.esi_client import (
    fetch_machine_snapshot,
    fetch_machines_snapshot,
    sync_cell_state,
)
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
    if normalized in ("vacant", "unassigned"):
        return LockerCellStatus.VACANT
    if normalized in ("occupied", "assigned"):
        return LockerCellStatus.OCCUPIED
    if normalized == "blocked":
        return LockerCellStatus.FAULT
    return None


async def _restore_forgotten_pickup_pins(
    db,
    candidates: list[LockerCell],
    now: datetime,
) -> None:
    """Возвращает PIN в ячейки, из которых постамат его потерял.

    Код попадает в железо один раз — при подтверждении брони. Сброс
    постамата (или любой перевод ячейки в свободную, при котором ESI
    затирает pin) оставляет клиента с кодом, которого на клавиатуре уже
    нет: приложение показывает 4 цифры, постамат их не принимает.

    Чиним сами: если ячейка числится за арендой, которая ещё ждёт выдачи,
    а постамат говорит «свободна» — записываем код заново. Это `set-cell`,
    он назначает состояние и код; ячейка при этом НЕ открывается, команда
    `/open-cell` отсюда не вызывается.
    """
    if not candidates:
        return

    cell_by_id = {cell.id: cell for cell in candidates}
    units = list(
        (
            await db.scalars(
                select(InventoryUnit).where(
                    InventoryUnit.locker_cell_id.in_(list(cell_by_id.keys()))
                )
            )
        ).all()
    )
    if not units:
        return

    rentals = list(
        (
            await db.scalars(
                select(Rental).where(
                    Rental.inventory_unit_id.in_([unit.id for unit in units]),
                    Rental.status.in_(
                        (RentalStatus.PICKUP_READY, RentalStatus.PICKUP_OPENED)
                    ),
                )
            )
        ).all()
    )
    if not rentals:
        return

    rental_by_unit = {rental.inventory_unit_id: rental for rental in rentals}
    for unit in units:
        cell = cell_by_id.get(unit.locker_cell_id)
        rental = rental_by_unit.get(unit.id)
        if cell is None or rental is None or not rental.pickup_pin:
            continue

        # Ячейку уже открывали после того, как аренда появилась — значит
        # товар, скорее всего, забрали, и возвращать код туда не нужно.
        if cell.last_opened_at is not None and ensure_utc(cell.last_opened_at) > ensure_utc(
            rental.created_at
        ):
            continue

        try:
            await sync_cell_state(
                db,
                locker_id=cell.locker_id,
                cell_id=cell.id,
                state="occupied",
                pin=rental.pickup_pin,
            )
        except Exception:
            logger.exception(
                "Failed to restore pickup PIN for cell %s (rental %s)",
                cell.id,
                rental.id,
            )
            continue

        cell.status = LockerCellStatus.RESERVED
        cell.last_event_at = now
        db.add(
            RentalEvent(
                rental_id=rental.id,
                event_type="pickup_pin_restored",
                from_status=rental.status,
                to_status=rental.status,
                source=RentalEventSource.SYSTEM,
                payload_json={
                    "cellId": str(cell.id),
                    "externalCellId": cell.external_cell_id,
                    "reason": "locker_reported_cell_vacant",
                },
            )
        )
        logger.info(
            "Restored pickup PIN in cell %s for rental %s", cell.id, rental.id
        )


async def _restore_forgotten_return_pins(
    db,
    candidates: list[LockerCell],
    now: datetime,
) -> None:
    """То же самое, но для возвратов: код сдачи тоже живёт в железе.

    Ячейку под возврат мы назначаем один раз — в момент, когда клиент
    нажал «Оформить возврат». Сброс постамата (или любой перевод ячейки
    в свободную, при котором ESI затирает pin) оставляет человека у
    постамата с кодом, которого на клавиатуре уже нет, а вещь — на руках.

    Чиним так же, как выдачу: если постамат говорит «ячейка свободна», а
    на неё есть живая заявка на возврат, записываем код заново. Это
    `set-cell`; ячейка при этом НЕ открывается, `/open-cell` отсюда не
    вызывается.
    """
    if not candidates:
        return

    cell_by_id = {cell.id: cell for cell in candidates}
    requests = list(
        (
            await db.scalars(
                select(ReturnRequest).where(
                    ReturnRequest.cell_id.in_(list(cell_by_id.keys())),
                    ReturnRequest.status.in_(
                        (
                            ReturnRequestStatus.CREATED,
                            ReturnRequestStatus.LOCKER_OPENED,
                            ReturnRequestStatus.AWAITING_CLOSE,
                        )
                    ),
                )
            )
        ).all()
    )

    active_statuses = (
        ReturnRequestStatus.CREATED,
        ReturnRequestStatus.LOCKER_OPENED,
        ReturnRequestStatus.AWAITING_CLOSE,
    )
    for request in requests:
        cell = cell_by_id.get(request.cell_id)
        if cell is None or not request.pin:
            continue

        # Сессия без autoflush: выборка выше могла прийти из БД, а в памяти
        # заявку уже уронил проход по дедлайнам в начале тика. Сверяемся с
        # объектом, а не с тем, что было в базе на момент SELECT.
        if request.status not in active_statuses:
            continue

        # Заявка уже протухла — её добьёт проход по дедлайнам, писать код
        # в ячейку под мёртвый возврат незачем.
        if ensure_utc(request.deadline_at) <= now:
            continue

        # Ячейку открывали после оформления возврата — товар, скорее всего,
        # уже внутри, и ждём только события о закрытии.
        if cell.last_opened_at is not None and ensure_utc(cell.last_opened_at) > ensure_utc(
            request.requested_at
        ):
            continue

        try:
            await sync_cell_state(
                db,
                locker_id=cell.locker_id,
                cell_id=cell.id,
                state="occupied",
                pin=request.pin,
            )
        except Exception:
            logger.exception(
                "Failed to restore return PIN for cell %s (return request %s)",
                cell.id,
                request.id,
            )
            continue

        cell.status = LockerCellStatus.RESERVED
        cell.last_event_at = now
        rental = await db.get(Rental, request.rental_id)
        if rental is not None:
            db.add(
                RentalEvent(
                    rental_id=rental.id,
                    event_type="return_pin_restored",
                    from_status=rental.status,
                    to_status=rental.status,
                    source=RentalEventSource.SYSTEM,
                    payload_json={
                        "returnRequestId": str(request.id),
                        "cellId": str(cell.id),
                        "externalCellId": cell.external_cell_id,
                        "reason": "locker_reported_cell_vacant",
                    },
                )
            )
        logger.info(
            "Restored return PIN in cell %s for return request %s", cell.id, request.id
        )


async def reconcile_esi_and_returns() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        confirmation_notifications: list[tuple[Rental, InventoryUnit, LockerLocation, LockerCell]] = []
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

        # Ячейки, которые постамат считает свободными: кандидаты на возврат
        # забытого PIN (см. `_restore_forgotten_pickup_pins`).
        pin_restore_candidates: list[LockerCell] = []
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
            # Игнорируем флаг 'online' в снапшоте ESI во избежание ложных блокировок.
            # Если ESI вернул снапшот, значит связь с ним есть, помечаем постамат как ONLINE.
            locker.status = LockerStatus.ONLINE

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

                # Постамат считает ячейку свободной: если за ней числится
                # аренда, ждущая выдачи, её PIN там уже стёрт — вернём.
                # Открытую ячейку не трогаем: там сейчас идёт выдача.
                snapshot_state = str(cell_snapshot.get("state") or "").strip().lower()
                if not open_flag and snapshot_state in ("vacant", "unassigned"):
                    pin_restore_candidates.append(cell)

        await _restore_forgotten_pickup_pins(db, pin_restore_candidates, now)
        await _restore_forgotten_return_pins(db, pin_restore_candidates, now)

        if not settings.ESI_DEV_STUB and settings.ESI_BASE_URL:
            active_requests = list((await db.scalars(active_requests_stmt)).all())
            for request in active_requests:
                if request.status not in (
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
                if not is_open and state in ("occupied", "assigned"):
                    rental, unit = await complete_return_request(
                        db,
                        request=request,
                        provider_event_id=f"reconcile:{request.id}:{int(now.timestamp())}",
                        source=RentalEventSource.SYSTEM,
                    )
                    if rental is not None and unit is not None:
                        confirmation_notifications.append((rental, unit, locker, cell))

        await db.commit()

        for rental, unit, locker, cell in confirmation_notifications:
            product = await db.get(Product, unit.product_id)
            if product is None:
                continue
            notify_inventory_awaiting_confirmation(
                product=product,
                locker=locker,
                cell=cell,
                unit=unit,
                rental=rental,
            )


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
