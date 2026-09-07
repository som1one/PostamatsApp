import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class InternalErrorResponseMiddleware:
    """Отдаёт JSON 500 изнутри CORS-мидлвари.

    Starlette обрабатывает необработанное исключение в ServerErrorMiddleware,
    а он стоит СНАРУЖИ CORSMiddleware — в такой ответ заголовок
    Access-Control-Allow-Origin уже не попадает. Браузер видит кросс-доменный
    ответ без CORS и роняет fetch с TypeError «Failed to fetch», пряча
    настоящую ошибку. Поэтому ловим исключение здесь: этот слой подключается
    ДО CORSMiddleware, то есть оказывается внутри неё, и заголовки на ответ
    навешиваются как обычно.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "unhandled error on %s %s",
                scope.get("method", "?"),
                scope.get("path", "?"),
            )
            if response_started:
                # Заголовки уже ушли — чинить нечего, пусть падает выше.
                raise
            response = JSONResponse({"detail": "INTERNAL_ERROR"}, status_code=500)
            await response(scope, receive, send)
