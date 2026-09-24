"""Картинка-капча для публичных форм — пока её спрашивает только обратная связь.

Токен ни к какой форме не привязан: он одноразовый, а ответ сверяет та
ручка, в которую капчу прислали. Как устроены токен и картинка — в
``backend/utils/captcha.py``.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from backend.utils.captcha import CAPTCHA_TTL_SECONDS, issue_captcha
from backend.utils.public_rate_limit import RateLimiter, client_ip


router = APIRouter(tags=["public-captcha"])

# Картинку рисуем на лету, поэтому флуд с одного адреса отсекаем. Запас
# большой: кнопка «другой код» и пара открытых вкладок в него укладываются,
# а общий потолок высокий, чтобы им нельзя было выключить форму всем.
_limiter = RateLimiter(
    per_ip=30,
    per_ip_window=10 * 60,
    global_limit=20_000,
    global_window=60 * 60,
)


@router.get("/api/captcha")
async def get_captcha(request: Request, response: Response):
    if not _limiter.allow(client_ip(request)):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "TOO_MANY_REQUESTS",
                "message": "Слишком много запросов. Попробуйте через несколько минут.",
            },
        )

    challenge = await run_in_threadpool(issue_captcha)
    # Картинка одноразовая: ни браузер, ни прокси не должны отдать её повторно.
    response.headers["Cache-Control"] = "no-store"
    return {
        "data": {
            "token": challenge.token,
            "image": challenge.image_data_url,
            "expiresIn": CAPTCHA_TTL_SECONDS,
        }
    }
