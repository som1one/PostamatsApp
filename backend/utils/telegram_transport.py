from backend.core.settings import settings


def telegram_api_url(method: str) -> str:
    if settings.TELEGRAM_RELAY_URL:
        return f"{settings.TELEGRAM_RELAY_URL}/api/{method}"
    return f"https://api.telegram.org/bot{settings.TELEGRAM_ADMIN_BOT_TOKEN}/{method}"


def telegram_api_headers() -> dict[str, str]:
    if settings.TELEGRAM_RELAY_URL and settings.TELEGRAM_RELAY_SECRET:
        return {"Authorization": f"Bearer {settings.TELEGRAM_RELAY_SECRET}"}
    return {}
