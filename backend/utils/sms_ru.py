import logging

import httpx

from backend.core.settings import settings


logger = logging.getLogger(__name__)

SMS_RU_SEND_URL = "https://sms.ru/sms/send"
AUTH_SMS_TEMPLATE = "Код входа в naprokatberu: {code}"


class SmsRuError(Exception):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


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


async def send_auth_code(phone: str, code: str) -> str | None:
    if not settings.SMS_RU_API_ID:
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 500)

    recipient = _normalize_sms_ru_phone(phone)
    params = {
        "api_id": settings.SMS_RU_API_ID,
        "to": recipient,
        "msg": AUTH_SMS_TEMPLATE.format(code=code),
        "json": 1,
    }
    if settings.SMS_RU_FROM:
        params["from"] = settings.SMS_RU_FROM

    try:
        async with httpx.AsyncClient(timeout=settings.SMS_RU_TIMEOUT_SECONDS) as client:
            response = await client.get(SMS_RU_SEND_URL, params=params)
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
        logger.warning("sms.ru returned unexpected payload type for %s", _mask_phone(recipient))
        raise SmsRuError("AUTH_SMS_PROVIDER_ERROR", 502)

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
    return str(sms_id) if sms_id is not None else None
