"""Фото вещи при возврате в постамат.

Клиент снимает вещь в открытой ячейке, грузит фото обычным presign+PUT
(kind ``condition_photo_after``) и присылает fileId в ``confirm-return``.
Здесь всё, что общее у клиентского API и админки: проверка файлов, запись
отчёта ``ConditionReport(AFTER_RETURN)`` и сериализация.

Отчёт привязан к аренде (колонки ``return_request_id`` в схеме нет),
связь с заявкой — только в payload события ``return_photos_attached``.
Отчёт без фото (клиент подтвердил с комментарием, когда камера не
сработала) остаётся открытым: фото к нему можно дослать, пока идёт окно.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import ClientError
from backend.core.settings import settings
from backend.models.condition_report import ConditionReport

# Импорт нужен не только ради запросов: backend.main этот модуль не тянет,
# и без него таблицы condition_report_photos нет в Base.metadata.
from backend.models.condition_report_photo import ConditionReportPhoto
from backend.models.enums import (
    ConditionReportType,
    MediaFileKind,
    RentalEventSource,
    RentalStatus,
    ReturnRequestStatus,
)
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.media_file import MediaFile
from backend.models.rental import Rental
from backend.models.rental_event import RentalEvent
from backend.models.return_request import ReturnRequest
from backend.utils.local_storage import local_upload_path
from backend.utils.products_utils import public_media_url
from backend.utils.reservation_utils import ensure_utc
from backend.utils.return_requests import ACTIVE_RETURN_REQUEST_STATUSES
from backend.utils.uploads_utils import EXTENSION_BY_MIME, MIME_BY_KIND, max_size_for_kind

RETURN_PHOTOS_MAX = 4
RETURN_PHOTO_NOTE_MAX = 500

RETURN_PHOTOS_ATTACHED_EVENT = "return_photos_attached"

# Расширения, под которыми фото возврата отдаются как картинка. Ключ со
# старым .svg/.html (presign до выравнивания расширения по MIME) StaticFiles
# отдал бы как документ на домене API — такие файлы в отчёт не берём.
_RETURN_PHOTO_SUFFIXES = frozenset(
    {".jpeg"}
    | {EXTENSION_BY_MIME[mime] for mime in MIME_BY_KIND[MediaFileKind.CONDITION_PHOTO_AFTER]}
)


class ReturnPhotoError(Exception):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass
class ReturnReportView:
    report: ConditionReport | None = None
    # Фото отчёта в порядке sort_order.
    photos: list[MediaFile] = field(default_factory=list)
    # Последняя COMPLETED-заявка: от её completed_at считается окно досылки.
    completed_return_request: ReturnRequest | None = None
    has_active_return_request: bool = False
    has_any_return_request: bool = False
    # Для квитанции: куда вернули вещь по последней COMPLETED-заявке.
    completed_locker_name: str | None = None
    completed_cell_label: str | None = None


def normalize_return_photo_ids(file_ids: Sequence[UUID] | None) -> list[UUID]:
    """Дедуп с сохранением порядка: клиент мог дважды прислать один кадр."""
    seen: set[UUID] = set()
    result: list[UUID] = []
    for file_id in file_ids or ():
        if file_id in seen:
            continue
        seen.add(file_id)
        result.append(file_id)
    return result


def normalize_return_note(note: str | None) -> str | None:
    if note is None:
        return None
    stripped = note.strip()
    return stripped or None


def _completed_sort_key(request: ReturnRequest) -> tuple[datetime, datetime]:
    floor = datetime.min.replace(tzinfo=timezone.utc)
    completed = ensure_utc(request.completed_at) if request.completed_at else floor
    created = ensure_utc(request.created_at) if request.created_at else floor
    return completed, created


async def load_return_report_views(
    db: AsyncSession,
    rental_ids: Sequence[UUID],
) -> dict[UUID, ReturnReportView]:
    """Отчёты и заявки возврата пачкой: три запроса на любое число аренд."""
    ids = list(dict.fromkeys(rental_ids))
    views: dict[UUID, ReturnReportView] = {rental_id: ReturnReportView() for rental_id in ids}
    if not ids:
        return views

    # Постамат и ячейку подтягиваем тем же запросом, что и заявки: квитанции
    # в списке аренд нужны их имена, а отдельный запрос на аренду — это N+1.
    request_rows = (
        await db.execute(
            select(ReturnRequest, LockerLocation.name, LockerCell.label)
            .outerjoin(LockerLocation, LockerLocation.id == ReturnRequest.locker_id)
            .outerjoin(LockerCell, LockerCell.id == ReturnRequest.cell_id)
            .where(ReturnRequest.rental_id.in_(ids))
        )
    ).all()
    for request, locker_name, cell_label in request_rows:
        view = views.get(request.rental_id)
        if view is None:
            continue
        view.has_any_return_request = True
        if request.status in ACTIVE_RETURN_REQUEST_STATUSES:
            view.has_active_return_request = True
        if request.status == ReturnRequestStatus.COMPLETED and (
            view.completed_return_request is None
            or _completed_sort_key(request) > _completed_sort_key(view.completed_return_request)
        ):
            view.completed_return_request = request
            view.completed_locker_name = locker_name
            view.completed_cell_label = cell_label

    # Отчёт на аренду один; если гонка всё же создала два — берём первый,
    # именно он ушёл операторам.
    reports = (
        await db.scalars(
            select(ConditionReport)
            .where(
                ConditionReport.rental_id.in_(ids),
                ConditionReport.report_type == ConditionReportType.AFTER_RETURN,
            )
            .order_by(ConditionReport.created_at.asc(), ConditionReport.id.asc())
        )
    ).all()
    report_ids: list[UUID] = []
    for report in reports:
        view = views.get(report.rental_id)
        if view is None or view.report is not None:
            continue
        view.report = report
        report_ids.append(report.id)

    if report_ids:
        view_by_report_id = {
            view.report.id: view for view in views.values() if view.report is not None
        }
        rows = (
            await db.execute(
                select(ConditionReportPhoto.condition_report_id, MediaFile)
                .join(MediaFile, MediaFile.id == ConditionReportPhoto.file_id)
                .where(ConditionReportPhoto.condition_report_id.in_(report_ids))
                .order_by(
                    ConditionReportPhoto.condition_report_id,
                    ConditionReportPhoto.sort_order.asc(),
                    ConditionReportPhoto.created_at.asc(),
                )
            )
        ).all()
        for report_id, media in rows:
            view = view_by_report_id.get(report_id)
            if view is not None:
                view.photos.append(media)

    return views


async def load_return_report_view(db: AsyncSession, rental_id: UUID) -> ReturnReportView:
    return (await load_return_report_views(db, [rental_id]))[rental_id]


async def load_latest_returned_rentals(
    db: AsyncSession,
    unit_ids: Sequence[UUID],
) -> dict[UUID, Rental]:
    """Последняя аренда каждого юнита, возвращённая через постамат.

    Именно её возврат перевёл юнит в «На проверке»: сетка ячеек показывает
    её фото, а карточка аренды — кнопки проверки только у неё. Один запрос
    на любое число юнитов.
    """
    ids = list(dict.fromkeys(unit_ids))
    if not ids:
        return {}

    rows = (
        await db.execute(
            select(Rental, ReturnRequest)
            .join(ReturnRequest, ReturnRequest.rental_id == Rental.id)
            .where(
                Rental.inventory_unit_id.in_(ids),
                ReturnRequest.status == ReturnRequestStatus.COMPLETED,
            )
            .order_by(
                ReturnRequest.completed_at.desc().nulls_last(),
                ReturnRequest.created_at.desc(),
            )
        )
    ).all()
    # Строки уже от свежих к старым — первая встреченная аренда юнита и есть последняя.
    rental_by_unit: dict[UUID, Rental] = {}
    for rental, _request in rows:
        rental_by_unit.setdefault(rental.inventory_unit_id, rental)
    return rental_by_unit


async def resolve_return_photo_files(
    db: AsyncSession,
    *,
    user_id: UUID,
    file_ids: Sequence[UUID],
    allow_attached_to_report_id: UUID | None = None,
) -> list[MediaFile]:
    """Проверяет присланные fileId и отдаёт MediaFile в порядке запроса.

    Ничего не меняет в базе — зовётся до перевода аренды, чтобы кривой файл
    не оставил возврат завершённым наполовину.
    """
    ids = normalize_return_photo_ids(file_ids)
    if len(ids) > RETURN_PHOTOS_MAX:
        raise ReturnPhotoError("RETURN_PHOTOS_TOO_MANY", 400)
    if not ids:
        return []

    allowed_mimes = MIME_BY_KIND[MediaFileKind.CONDITION_PHOTO_AFTER]
    media_by_id = {
        media.id: media
        for media in (await db.scalars(select(MediaFile).where(MediaFile.id.in_(ids)))).all()
    }
    files: list[MediaFile] = []
    for file_id in ids:
        media = media_by_id.get(file_id)
        if (
            media is None
            or media.kind != MediaFileKind.CONDITION_PHOTO_AFTER
            or media.uploaded_by_user_id != user_id
            or media.mime_type not in allowed_mimes
            or PurePosixPath(media.file_key).suffix.lower() not in _RETURN_PHOTO_SUFFIXES
        ):
            raise ReturnPhotoError("RETURN_PHOTO_INVALID", 400)
        files.append(media)

    # Один кадр — один отчёт: иначе старое фото можно выдать за новый возврат.
    attached = (
        await db.execute(
            select(ConditionReportPhoto.condition_report_id).where(
                ConditionReportPhoto.file_id.in_(ids)
            )
        )
    ).scalars().all()
    for report_id in attached:
        if allow_attached_to_report_id is None or report_id != allow_attached_to_report_id:
            raise ReturnPhotoError("RETURN_PHOTO_INVALID", 400)

    # Presign создаёт запись до того, как пришли байты. На filesystem (прод)
    # проверяем, что PUT действительно дошёл; у stub/s3 проверить нечем.
    max_size = max_size_for_kind(MediaFileKind.CONDITION_PHOTO_AFTER)
    for media in files:
        if media.storage_provider != "filesystem":
            continue
        try:
            path = local_upload_path(media.file_key)
        except ClientError as exc:
            raise ReturnPhotoError("RETURN_PHOTO_INVALID", 400) from exc
        if not path.is_file():
            raise ReturnPhotoError("RETURN_PHOTO_NOT_UPLOADED", 409)
        # Файлы, залитые до лимита на PUT, могут быть любого размера —
        # операторам такое не отправить, а в память уведомления не влезет.
        if path.stat().st_size > max_size:
            raise ReturnPhotoError("RETURN_PHOTO_INVALID", 400)

    return files


def _add_report_photos_and_event(
    db: AsyncSession,
    *,
    rental: Rental,
    report: ConditionReport,
    files: Sequence[MediaFile],
    return_request: ReturnRequest | None,
) -> None:
    for index, media in enumerate(files):
        db.add(
            ConditionReportPhoto(
                condition_report_id=report.id,
                file_id=media.id,
                sort_order=index,
            )
        )

    db.add(
        RentalEvent(
            rental_id=rental.id,
            event_type=RETURN_PHOTOS_ATTACHED_EVENT,
            from_status=rental.status,
            to_status=rental.status,
            source=RentalEventSource.USER,
            payload_json={
                "conditionReportId": str(report.id),
                "returnRequestId": str(return_request.id) if return_request is not None else None,
                "photoCount": len(files),
                "fileIds": [str(media.id) for media in files],
            },
        )
    )


async def create_return_report(
    db: AsyncSession,
    *,
    rental: Rental,
    user_id: UUID,
    files: Sequence[MediaFile],
    note: str | None,
    return_request: ReturnRequest | None,
) -> ConditionReport:
    """Пишет отчёт, фото и событие аренды. Commit — на вызывающем."""
    report = ConditionReport(
        inventory_unit_id=rental.inventory_unit_id,
        rental_id=rental.id,
        report_type=ConditionReportType.AFTER_RETURN,
        note=note,
        created_by_user_id=user_id,
    )
    db.add(report)
    await db.flush()

    _add_report_photos_and_event(
        db,
        rental=rental,
        report=report,
        files=files,
        return_request=return_request,
    )
    await db.flush()
    return report


async def attach_photos_to_return_report(
    db: AsyncSession,
    *,
    rental: Rental,
    report: ConditionReport,
    files: Sequence[MediaFile],
    note: str | None,
    return_request: ReturnRequest | None,
) -> ConditionReport:
    """Досылает фото в отчёт, который клиент отправил без фото.

    Непустой комментарий заменяет прежний. Commit — на вызывающем.
    """
    if note is not None:
        report.note = note
    _add_report_photos_and_event(
        db,
        rental=rental,
        report=report,
        files=files,
        return_request=return_request,
    )
    await db.flush()
    return report


def return_photo_window_end(view: ReturnReportView) -> datetime | None:
    request = view.completed_return_request
    if request is None or request.completed_at is None:
        return None
    return ensure_utc(request.completed_at) + timedelta(
        minutes=settings.RETURN_PHOTO_LATE_WINDOW_MINUTES
    )


def open_late_photo_window_end(
    rental: Rental,
    view: ReturnReportView,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """До какого момента сервер ещё примет фото к завершённому возврату.

    None — не примет: аренда не закрыта через постамат, фото уже есть или
    окно истекло. Правило одно для клиента и для админки.
    """
    if rental.status != RentalStatus.COMPLETED or view.photos:
        return None
    window_end = return_photo_window_end(view)
    if window_end is None:
        return None
    current = ensure_utc(now) if now is not None else datetime.now(timezone.utc)
    return window_end if current <= window_end else None


def _iso(value: datetime | None) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def serialize_client_return_report(
    rental: Rental,
    view: ReturnReportView,
    *,
    now: datetime | None = None,
) -> dict | None:
    if view.report is None and not view.has_any_return_request:
        return None

    completed_request = view.completed_return_request
    payload = {
        "photos": [],
        "note": None,
        "submittedAt": None,
        "canAttachPhotos": False,
        "attachPhotosUntil": None,
        "maxPhotos": RETURN_PHOTOS_MAX,
        # Квитанция: куда и когда вернули — по последней завершённой заявке.
        "lockerName": view.completed_locker_name if completed_request is not None else None,
        "cellLabel": view.completed_cell_label if completed_request is not None else None,
        "returnedAt": _iso(completed_request.completed_at) if completed_request is not None else None,
    }

    if view.report is not None:
        payload["photos"] = [
            {"id": str(media.id), "url": public_media_url(media.file_key)}
            for media in view.photos
        ]
        payload["note"] = view.report.note
        payload["submittedAt"] = _iso(view.report.created_at)

    if rental.status == RentalStatus.RETURN_IN_PROGRESS and view.has_active_return_request:
        payload["canAttachPhotos"] = True
        return payload

    # Завершено дверцей или отчёт ушёл без фото — фото ещё ждём, пока идёт окно.
    # INCIDENT, окно истекло, force-complete, фото уже есть: не принимаем.
    window_end = open_late_photo_window_end(rental, view, now=now)
    if window_end is not None:
        payload["canAttachPhotos"] = True
        payload["attachPhotosUntil"] = window_end.isoformat()
    return payload


def serialize_admin_return_report(
    rental: Rental,
    view: ReturnReportView,
    *,
    pending_review: bool = False,
    now: datetime | None = None,
) -> dict | None:
    """Отчёт для операторов.

    ``pending_review`` считает вызывающий: юнит «На проверке» и эта аренда —
    последняя, вернувшая его через постамат. Иначе кнопки проверки на
    карточке старой аренды подтвердили бы чужой, более свежий возврат.
    """
    request = view.completed_return_request
    if view.report is None and request is None:
        return None

    returned_at = request.completed_at if request is not None else rental.completed_at
    # Пока окно открыто, «без фото» — ещё не приговор: клиент может дослать.
    window_end = open_late_photo_window_end(rental, view, now=now)
    attach_photos_until = window_end.isoformat() if window_end is not None else None
    if view.report is None:
        # Возврат прошёл через постамат, а фото клиент так и не прислал —
        # операторы видят «Без фото».
        return {
            "id": None,
            "createdAt": None,
            "note": None,
            "source": None,
            "photos": [],
            "photoCount": 0,
            "expected": True,
            "returnedAt": _iso(returned_at),
            "pendingReview": pending_review,
            "attachPhotosUntil": attach_photos_until,
        }

    report = view.report
    if report.created_by_user_id is not None:
        source = RentalEventSource.USER.value
    elif report.created_by_admin_id is not None:
        source = RentalEventSource.ADMIN.value
    else:
        source = None

    return {
        "id": str(report.id),
        "createdAt": _iso(report.created_at),
        "note": report.note,
        "source": source,
        "photos": [
            {
                "id": str(media.id),
                "url": public_media_url(media.file_key),
                "mimeType": media.mime_type,
                "fileSize": media.file_size,
            }
            for media in view.photos
        ],
        "photoCount": len(view.photos),
        "expected": request is not None,
        "returnedAt": _iso(returned_at),
        "pendingReview": pending_review,
        "attachPhotosUntil": attach_photos_until,
    }
