"""Интеграция с sms.ru.

Поддерживает два канала доставки кода:

- ``sms`` — обычный SMS с заранее сгенерированным нашим кодом.
- ``call`` — авторизация по звонку: sms.ru делает короткий вызов на
  номер пользователя, последние 4 цифры номера-источника и есть код.
  Код **возвращает sms.ru** в теле ответа, мы потом используем его как
  истину. Канал не требует согласования отправителя у операторов и
  обычно дешевле.

Какой канал использовать — управляется ``settings.SMS_RU_AUTH_MODE``
(``sms`` | ``call``). По умолчанию ``sms``.
"""

import logging

import httpx

from backend.core.settings import settings


logger = logging.getLogger(__name__)

SMS_RU_SEND_URL = "https://sms.ru/sms/send"
SMS_RU_CALL_URL = "https://sms.ru/code/call"
AUTH_SMS_TEMPLATE = "Код входа в naprokatberu: {code}"


class SmsRuError(Exception):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class AuthChannelResult:
    """Результат отправки кода через sms.ru.

    - ``channel`` — какой канал реально использовали (``sms`` или ``call``).
    - ``provider_id`` — идентификатор отправки на стороне sms.ru
      (``sms_id`` или ``call_id``), может быть ``None``.
    - ``code`` — для канала ``call`` это сгенерированный sms.ru код
      (последние 4 цифры исходящего номера). Для ``sms`` — ``None``,
      потому что код мы знали заранее.
    """

    __slots__ = ("channel", "provider_id", "code")

    def __init__(
        self,
        channel: str,
        provider_id: str | None,
        code: str | None = None,
    ) -> None:
        self.channel = channel
        self.provider_id = provider_id
        self.code = code


def _mask_phone(phone: str) -> str:
    digits = "".join(symbol for symbol in phone if symbol.isdigit())
    if len(digits) <= 4:
        return digits
    return f"{digits[:2]}***{digits[-2:]}"


def _normalize_sms_ru_phone(phone: str) -> str:
    return "".join(symbol for symbol in phone if symbol.isdigit())


def _coerce_status_code(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _http_get_json(url: str, params: dict[str, object], recipient: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.SMS_RU_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
    except httpx.RequestError:
        logger.exception("sms.ru request failed for %s", _mask_phone(recipient))
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 502) from None

    if response.status_code >= 400:
        logger.warning(
            "sms.ru HTTP error for %s: %s",
            _mask_phone(recipient),
            response.status_code,
        )
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 502)

    try:
        payload = response.json()
    except ValueError:
        logger.warning("sms.ru returned invalid JSON for %s", _mask_phone(recipient))
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 502) from None

    if not isinstance(payload, dict):
        logger.warning(
            "sms.ru returned unexpected payload type for %s", _mask_phone(recipient)
        )
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 502)

    return payload


async def _send_via_sms(phone: str, code: str) -> AuthChannelResult:
    recipient = _normalize_sms_ru_phone(phone)
    params: dict[str, object] = {
        "api_id": settings.SMS_RU_API_ID,
        "to": recipient,
        "msg": AUTH_SMS_TEMPLATE.format(code=code),
        "json": 1,
    }
    if settings.SMS_RU_FROM:
        params["from"] = settings.SMS_RU_FROM

    payload = await _http_get_json(SMS_RU_SEND_URL, params, recipient)

    if payload.get("status") != "OK" or _coerce_status_code(payload.get("status_code")) != 100:
        logger.warning(
            "sms.ru top-level send failed for %s: %s",
            _mask_phone(recipient),
            payload.get("status_code"),
        )
        raise SmsRuError("AUTH_SMS_SEND_FAILED", 502)

    sms_payload = payload.get("sms")
    if not isinstance(sms_payload, dict):
        logger.warning("sms.ru response missing sms map for %s", _mask_phone(recipient))
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 502)

    recipient_payload = sms_payload.get(recipient)
    if not isinstance(recipient_payload, dict):
        logger.warning(
            "sms.ru response missing recipient status for %s",
            _mask_phone(recipient),
        )
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 502)

    if recipient_payload.get("status") != "OK" or _coerce_status_code(
        recipient_payload.get("status_code")
    ) != 100:
        logger.warning(
            "sms.ru recipient send failed for %s: %s",
            _mask_phone(recipient),
            recipient_payload.get("status_code"),
        )
        raise SmsRuError("AUTH_SMS_SEND_FAILED", 502)

    sms_id = recipient_payload.get("sms_id")
    return AuthChannelResult(
        channel="sms",
        provider_id=str(sms_id) if sms_id is not None else None,
    )


async def _send_via_call(phone: str) -> AuthChannelResult:
    """Звонок-авторизация: sms.ru сам генерирует код и звонит на номер.

    Sms.ru возвращает в JSON поле ``code`` — это и есть число, последние
    4 цифры номера, с которого звонят пользователю. Этим кодом мы потом
    проверяем `confirm-code`.
    """

    recipient = _normalize_sms_ru_phone(phone)
    params: dict[str, object] = {
        "api_id": settings.SMS_RU_API_ID,
        "phone": recipient,
        "json": 1,
    }
    payload = await _http_get_json(SMS_RU_CALL_URL, params, recipient)

    if payload.get("status") != "OK" or _coerce_status_code(payload.get("status_code")) != 100:
        logger.warning(
            "sms.ru call_password failed for %s: %s",
            _mask_phone(recipient),
            payload.get("status_code"),
        )
        raise SmsRuError("AUTH_SMS_SEND_FAILED", 502)

    raw_code = payload.get("code")
    code = str(raw_code).strip() if raw_code is not None else ""
    if not code or not code.isdigit():
        logger.warning(
            "sms.ru call_password did not return a valid code for %s",
            _mask_phone(recipient),
        )
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 502)

    call_id = payload.get("call_id") or payload.get("id")
    return AuthChannelResult(
        channel="call",
        provider_id=str(call_id) if call_id is not None else None,
        code=code,
    )


async def send_auth_code(phone: str, code: str) -> AuthChannelResult:
    """Отправляет код пользователю.

    Если включён режим ``call``, ``code`` игнорируется (sms.ru сам
    решает, какие цифры пользователь увидит на экране звонка) и в
    результате будет ``AuthChannelResult.code`` — этот код надо
    использовать как новую истину для проверки.

    Возвращает :class:`AuthChannelResult`.
    """

    if not settings.SMS_RU_API_ID:
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 500)

    mode = (settings.SMS_RU_AUTH_MODE or "sms").lower()
    if mode == "call":
        return await _send_via_call(phone)
    return await _send_via_sms(phone, code)
