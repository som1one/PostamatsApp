"""CRUD по админским подписчикам MAX.

Зеркало :mod:`backend.routers.admin.telegram_subscribers`: под капотом —
:mod:`backend.utils.max_admin_subscribers`, здесь только трансляция
HTTP ↔ сервис и единая обработка ошибок.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.city import City
from backend.routers.admin.auth import get_current_admin
from backend.utils.admin_scope import franchise_city_id, require_not_franchise
from backend.utils.max_admin_subscribers import (
    SubscriberError,
    create_subscriber,
    delete_max_webhook,
    delete_subscriber,
    get_max_webhook_info,
    list_subscribers,
    resync_chat_ids,
    serialize_subscriber,
    set_max_webhook,
    update_subscriber,
)

router = APIRouter(
    prefix="/api/admin/max-subscribers",
    tags=["admin-max-subscribers"],
)


class CreateSubscriberPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=200)
    isEnabled: bool = True


class UpdateSubscriberPayload(BaseModel):
    isEnabled: bool | None = None
    note: str | None = Field(default=None, max_length=200)


def _to_http(error: SubscriberError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.code)


async def _city_names(db: AsyncSession, rows) -> dict:
    city_ids = {row.city_id for row in rows if row.city_id}
    if not city_ids:
        return {}
    cities = (await db.scalars(select(City).where(City.id.in_(city_ids)))).all()
    return {city.id: city.name for city in cities}


async def _serialize_rows(db: AsyncSession, rows) -> list[dict]:
    names = await _city_names(db, rows)
    return [serialize_subscriber(row, names.get(row.city_id)) for row in rows]


@router.get("")
async def list_max_subscribers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    rows = await list_subscribers(db, city_id=franchise_city_id(admin))
    return {"data": {"items": await _serialize_rows(db, rows)}}


@router.post("")
async def create_max_subscriber(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: CreateSubscriberPayload = Body(...),
):
    admin, _ = await get_current_admin(request, db)
    # Франшиза не выбирает город — подписчик автоматически привязывается
    # к её городу и получает только его события.
    city_id = franchise_city_id(admin)
    try:
        subscriber = await create_subscriber(
            db,
            username=payload.username,
            note=payload.note,
            is_enabled=payload.isEnabled,
            city_id=city_id,
        )
    except SubscriberError as exc:
        raise _to_http(exc) from exc

    city = await db.get(City, city_id) if city_id else None
    return {
        "data": {
            "subscriber": serialize_subscriber(subscriber, city.name if city else None)
        }
    }


@router.patch("/{subscriber_id}")
async def patch_max_subscriber(
    request: Request,
    subscriber_id: UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    payload: UpdateSubscriberPayload = Body(...),
):
    admin, _ = await get_current_admin(request, db)
    try:
        subscriber = await update_subscriber(
            db,
            subscriber_id,
            is_enabled=payload.isEnabled,
            note=payload.note,
            require_city_id=franchise_city_id(admin),
        )
    except SubscriberError as exc:
        raise _to_http(exc) from exc

    city = await db.get(City, subscriber.city_id) if subscriber.city_id else None
    return {
        "data": {
            "subscriber": serialize_subscriber(subscriber, city.name if city else None)
        }
    }


@router.delete("/{subscriber_id}")
async def delete_max_subscriber(
    request: Request,
    subscriber_id: UUID = Path(...),
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    try:
        await delete_subscriber(
            db, subscriber_id, require_city_id=franchise_city_id(admin)
        )
    except SubscriberError as exc:
        raise _to_http(exc) from exc

    return {"data": {"deleted": True}}


@router.post("/resync")
async def resync_max_subscribers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Сматчить username-ы с идентификаторами диалогов из свежих апдейтов."""

    admin, _ = await get_current_admin(request, db)
    scope_city_id = franchise_city_id(admin)
    try:
        report = await resync_chat_ids(db)
    except SubscriberError as exc:
        raise _to_http(exc) from exc

    items = await list_subscribers(db, city_id=scope_city_id)
    if scope_city_id is not None:
        # Отчёт по всей сети франшизе не показываем — только её username-ы.
        own = {row.username for row in items}
        report = {
            **report,
            "missing": [name for name in report.get("missing", []) if name in own],
        }
    return {
        "data": {
            "report": report,
            "items": await _serialize_rows(db, items),
        }
    }


@router.post("/webhook")
async def setup_max_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Регистрирует webhook-подписку у MAX.

    База берётся из ADMIN_PANEL_URL, а если он не задан — из публичного
    origin текущего запроса (на проде это домен админки за Caddy).
    """

    admin, _ = await get_current_admin(request, db)
    require_not_franchise(admin)
    # request.base_url учитывает X-Forwarded-* за обратным прокси Caddy.
    origin = str(request.base_url).rstrip("/") if request.base_url else None
    try:
        result = await set_max_webhook(public_origin=origin)
    except SubscriberError as exc:
        raise _to_http(exc) from exc
    return {"data": result}


@router.get("/webhook")
async def get_max_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    require_not_franchise(admin)
    try:
        result = await get_max_webhook_info()
    except SubscriberError as exc:
        raise _to_http(exc) from exc
    return {"data": result}


@router.delete("/webhook")
async def remove_max_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin, _ = await get_current_admin(request, db)
    require_not_franchise(admin)
    origin = str(request.base_url).rstrip("/") if request.base_url else None
    try:
        result = await delete_max_webhook(public_origin=origin)
    except SubscriberError as exc:
        raise _to_http(exc) from exc
    return {"data": result}
