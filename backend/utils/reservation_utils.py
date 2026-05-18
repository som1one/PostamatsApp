import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from backend.models.enums import VerificationStatus
from backend.models.user import User
from backend.utils.auth_utils import ensure_user_not_blocked


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ensure_reservable_user(user: User) -> None:
    ensure_user_not_blocked(user)
    if user.verification_status != VerificationStatus.APPROVED:
        raise HTTPException(status_code=403, detail="USER_NOT_VERIFIED")


def calculate_expires_at(now: datetime, pickup_window_minutes: int) -> datetime:
    return now + timedelta(minutes=pickup_window_minutes)


def calculate_planned_end_at(starts_at: datetime, duration_type: str, duration_value: int) -> datetime:
    normalized_type = duration_type.strip().lower()
    if normalized_type == "hour":
        return starts_at + timedelta(hours=duration_value)
    if normalized_type == "week":
        return starts_at + timedelta(weeks=duration_value)
    if normalized_type == "month":
        return starts_at + timedelta(days=30 * duration_value)
    return starts_at + timedelta(days=duration_value)


def generate_pickup_pin() -> str:
    return f"{secrets.randbelow(10000):04d}"


# Сколько минут даётся пользователю на получение товара после оплаты/подтверждения аренды.
# По требованию: 3 часа.
PICKUP_WINDOW_MINUTES = 180


def calculate_pickup_expires_at(now: datetime) -> datetime:
    return now + timedelta(minutes=PICKUP_WINDOW_MINUTES)
