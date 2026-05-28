"""CRUD по админским Telegram-подписчикам.

Под капотом — :mod:`backend.utils.telegram_admin_subscribers`. Здесь
только трансляция HTTP ↔ сервис и единая обработка ошибок.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.routers.admin.auth import get_current_admin
from backend.utils.telegram_admin_subscribers import (
    SubscriberError,
    create_subscriber,
    delete_subscriber,
    list_subscribers,
    resync_chat_ids,
    serialize_subscriber,
    update_subscriber,
)

router = APIRouter(
    prefix="/api/admin/telegram-subscribers",
    tags=["admin-telegram-subscribers"],
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


@router.get("")
async def list_telegram_subscribers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)
    rows = await list_subscribers(db)
    return {"data": {"items": [serialize_subscriber(row) for row in rows]}}


@router.post("")
async def create_telegram_subscriber(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: CreateSubscriberPayload = Body(...),
):
    await get_current_admin(request, db)
    try:
        subscriber = await create_subscriber(
            db,
            username=payload.username,
            note=payload.note,
            is_enabled=payload.isEnabled,
        )
    except SubscriberError as exc:
        raise _to_http(exc) from exc

    return {"data": {"subscriber": serialize_subscriber(subscriber)}}


@router.patch("/{subscriber_id}")
async def patch_telegram_subscriber(
    request: Request,
    subscriber_id: UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    payload: UpdateSubscriberPayload = Body(...),
):
    await get_current_admin(request, db)
    try:
        subscriber = await update_subscriber(
            db,
            subscriber_id,
            is_enabled=payload.isEnabled,
            note=payload.note,
        )
    except SubscriberError as exc:
        raise _to_http(exc) from exc

    return {"data": {"subscriber": serialize_subscriber(subscriber)}}


@router.delete("/{subscriber_id}")
async def delete_telegram_subscriber(
    request: Request,
    subscriber_id: UUID = Path(...),
    db: AsyncSession = Depends(get_db),
):
    await get_current_admin(request, db)
    try:
        await delete_subscriber(db, subscriber_id)
    except SubscriberError as exc:
        raise _to_http(exc) from exc

    return {"data": {"deleted": True}}


@router.post("/resync")
async def resync_telegram_subscribers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Сматчить username-ы с chat_id из последних апдейтов бота."""

    await get_current_admin(request, db)
    try:
        report = await resync_chat_ids(db)
    except SubscriberError as exc:
        raise _to_http(exc) from exc

    items = await list_subscribers(db)
    return {
        "data": {
            "report": report,
            "items": [serialize_subscriber(row) for row in items],
        }
    }
