"""Webhook-эндпоинт для входящих апдейтов бота уведомлений в MAX.

Безопасность:

- URL содержит ``MAX_WEBHOOK_SECRET`` как path-сегмент — это основная
  проверка (MAX не подписывает запросы).
- Если MAX прислал заголовок ``X-Max-Bot-Api-Secret`` (он это делает,
  когда подписка создана с ``secret``), сверяем и его. Пустой заголовок
  не отвергаем: подписку могли создать вручную без секрета, и тогда
  единственный секрет — в пути.
- Без ``MAX_WEBHOOK_SECRET`` в настройках эндпоинт отвечает 503, чтобы
  случайно не оставить бота открытым на проде.

Webhook не требует админ-JWT: его дёргает сам MAX. Ошибки обработчика не
отдаём наружу, иначе MAX будет ретраить один и тот же апдейт (до 10 раз).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.settings import settings
from backend.utils.max_admin_subscribers import handle_max_update

router = APIRouter(prefix="/max", tags=["max-webhook"])

logger = logging.getLogger(__name__)


@router.post("/webhook/{secret}")
async def max_webhook(
    request: Request,
    secret: str = Path(..., min_length=1, max_length=256),
    db: AsyncSession = Depends(get_db),
    update: dict = Body(default_factory=dict),
):
    expected = settings.MAX_WEBHOOK_SECRET
    if not expected:
        raise HTTPException(status_code=503, detail="WEBHOOK_NOT_CONFIGURED")

    header_secret = request.headers.get("x-max-bot-api-secret") or ""
    if secret != expected or (header_secret and header_secret != expected):
        raise HTTPException(status_code=401, detail="WEBHOOK_SECRET_MISMATCH")

    try:
        result = await handle_max_update(db, update)
    except Exception:
        # Никогда не пробрасываем наружу — иначе MAX будет ретраить
        # один и тот же апдейт.
        logger.exception("Failed to handle MAX update")
        return {"ok": True, "handled": False}

    return {"ok": True, **result}
