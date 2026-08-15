"""Публичная заявка на франшизу (страница /franchise).

Заявка — такая же обратная связь, как идея для аренды, поэтому она
сохраняется в ``feedback_messages`` (раздел «Обратная связь» в админке) с
темой ``franchise`` и уходит админам в Telegram и MAX — тем же подписчикам,
что получают верификации и поддержку. Заявку, которая не доехала до
мессенджеров (нет токена, никто не подписан, API ответил ошибкой),
дублируем в лог на уровне ERROR: в админке она уже есть, но лид ждать не
любит.

Эндпоинт публичный и шлёт сообщения в мессенджер, то есть это удобная
мишень для спама — отсюда лимитер из
:mod:`backend.utils.public_rate_limit`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.enums import FeedbackTopic
from backend.models.feedback_message import FeedbackMessage
from backend.routers.feedback import resolve_source
from backend.utils.phone_utils import normalize_phone_for_storage
from backend.utils.admin_notifications import notify_admins
from backend.utils.feedback_notifications import build_feedback_notification
from backend.utils.public_rate_limit import RateLimiter, client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/franchise", tags=["public-franchise"])

_limiter = RateLimiter(
    per_ip=3,
    per_ip_window=10 * 60,
    global_limit=30,
    global_window=60 * 60,
)

# Минимум цифр в телефоне: 10 — это номер без кода страны (9991234567).
_MIN_PHONE_DIGITS = 10
_MAX_PHONE_DIGITS = 15


class FranchiseLeadPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    # Длину телефона проверяет _normalize_phone: так короткий номер даёт
    # понятный INVALID_PHONE, а не 422 от pydantic, который фронт покажет
    # общей ошибкой «не удалось отправить».
    phone: str = Field(..., min_length=1, max_length=32)
    city: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=32)


def _normalize_phone(raw: str) -> str:
    """Приводит телефон к виду, по которому менеджер сразу позвонит.

    Форму заполняют как привыкли — «8 900 123-45-67» или «9001234567».
    Считаем такие номера российскими и дотягиваем до +7: иначе в телегу
    прилетит нечто вроде «+89001234567», по чему не наберёшь в один тап.
    """

    try:
        phone = normalize_phone_for_storage(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="INVALID_PHONE") from exc

    digits = "".join(ch for ch in phone if ch.isdigit())
    if not (_MIN_PHONE_DIGITS <= len(digits) <= _MAX_PHONE_DIGITS):
        raise HTTPException(status_code=400, detail="INVALID_PHONE")

    if len(digits) == 11 and digits.startswith("8"):
        return f"+7{digits[1:]}"
    if len(digits) == 10:
        return f"+7{digits}"
    return phone


@router.post("/leads")
async def create_franchise_lead(
    request: Request,
    payload: FranchiseLeadPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    name = payload.name.strip()
    city = (payload.city or "").strip() or None
    comment = (payload.comment or "").strip() or None
    if not name:
        raise HTTPException(status_code=400, detail="INVALID_PAYLOAD")
    phone = _normalize_phone(payload.phone)

    if not _limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="TOO_MANY_REQUESTS")

    record = FeedbackMessage(
        topic=FeedbackTopic.FRANCHISE.value,
        source=resolve_source(payload.source),
        name=name,
        phone=phone,
        city=city,
        # Комментарий необязателен, а тело обращения — нет: без текста в
        # карточке остаётся понятная строка, а не пустое место.
        message=comment or "Заявка на франшизу без комментария",
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    lead_log = f"name={name!r} phone={phone!r} city={city!r} comment={comment!r}"
    logger.info("Franchise lead: %s", lead_log)

    text, buttons = build_feedback_notification(record)
    delivered = await notify_admins(text, buttons=buttons)
    if not delivered:
        # Посетителю всё равно отвечаем успехом: заявку он отправил, а
        # разбираться с ботом — наша забота. Уровень ERROR здесь не для
        # драмы: приложение не настраивает logging, INFO-строки в вывод
        # контейнера не попадают, а лид, не доехавший до мессенджеров,
        # должен быть виден в логе (в админке он уже сохранён).
        logger.error("Franchise lead NOT delivered to admins: %s", lead_log)

    return {"data": {"delivered": delivered, "id": str(record.id)}}
