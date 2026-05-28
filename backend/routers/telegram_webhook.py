"""Webhook-эндпоинт для входящих апдейтов от Telegram-бота уведомлений.

Безопасность:

- URL содержит ``TELEGRAM_WEBHOOK_SECRET`` как path-сегмент.
- Дополнительно валидируем заголовок ``X-Telegram-Bot-Api-Secret-Token``
  (его Telegram присылает, если мы передали ``secret_token`` в
  ``setWebhook``). Если токен не задан в настройках — эндпоинт
  отвечает 503, чтобы случайно не оставить бота открытым на проде.

Webhook не требует админ-JWT: его дёргает сама телега. Ошибки
обработчика не отдаём наружу, чтобы Telegram не ретраил бесконечно —
вместо этого логируем и возвращаем 200.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.settings import settings
from backend.utils.telegram_admin_subscribers import handle_telegram_update

router = APIRouter(prefix="/telegram", tags=["telegram-webhook"])

logger = logging.getLogger(__name__)


@router.post("/webhook/{secret}")
async def telegram_webhook(
    request: Request,
    secret: str = Path(..., min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
    update: dict = Body(default_factory=dict),
):
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    if not expected:
        raise HTTPException(status_code=503, detail="WEBHOOK_NOT_CONFIGURED")

    # Сравниваем оба места: path-сегмент и заголовок Telegram. Любое
    # несовпадение — 401, чтобы случайные пробы не получали ответы.
    header_secret = request.headers.get("x-telegram-bot-api-secret-token") or ""
    if secret != expected or header_secret != expected:
        raise HTTPException(status_code=401, detail="WEBHOOK_SECRET_MISMATCH")

    try:
        result = await handle_telegram_update(db, update)
    except Exception:
        # Никогда не пробрасываем наружу — иначе телега будет ретраить
        # один и тот же апдейт.
        logger.exception("Failed to handle telegram update")
        return {"ok": True, "handled": False}

    return {"ok": True, **result}
