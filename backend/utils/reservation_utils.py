import secrets
from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException

from backend.models.enums import VerificationStatus
from backend.models.user import User
from backend.utils.auth_utils import ensure_user_not_blocked


# Часовой пояс, в котором считаются календарные дни аренды.
# Россия с 2014 года без DST, поэтому фиксированное смещение корректно
# и не требует tzdata в контейнере. Если когда-то понадобится считать
# дни относительно города (Калининград, Владивосток и т.д.), это место
# заменится на city.timezone.
LOCAL_DAY_TZ = timezone(timedelta(hours=3), name="Europe/Moscow")


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


def _end_of_local_day_after(starts_at: datetime, days: int) -> datetime:
    """Возвращает 23:59:59 локального дня, наступающего через `days` суток
    после локальной даты `starts_at`.

    То есть аренда на 1 день, начатая 18.06, заканчивается 19.06 в 23:59:59.
    Аренда на 2 дня — 20.06 в 23:59:59 и так далее.
    Результат возвращается в UTC.
    """
    starts_local = ensure_utc(starts_at).astimezone(LOCAL_DAY_TZ)
    last_day_local = (starts_local + timedelta(days=max(days, 1))).date()
    end_local = datetime.combine(last_day_local, time(23, 59, 59), tzinfo=LOCAL_DAY_TZ)
    return end_local.astimezone(timezone.utc)


def calculate_planned_end_at(starts_at: datetime, duration_type: str, duration_value: int) -> datetime:
    normalized_type = duration_type.strip().lower()
    if normalized_type == "hour":
        return starts_at + timedelta(hours=duration_value)
    if normalized_type == "week":
        # Неделя = 7 календарных дней. Считаем по календарной дате, чтобы
        # пользователь не получал deadline в неудобное ночное время.
        return _end_of_local_day_after(starts_at, 7 * duration_value)
    if normalized_type == "month":
        # Месяц = 30 календарных дней (исторически принятая в проекте мера).
        return _end_of_local_day_after(starts_at, 30 * duration_value)
    return _end_of_local_day_after(starts_at, duration_value)


def generate_pickup_pin() -> str:
    return f"{secrets.randbelow(10000):04d}"


# Сколько минут даётся пользователю на получение товара после оплаты/подтверждения аренды.
# По требованию: 3 часа.
PICKUP_WINDOW_MINUTES = 180


def calculate_pickup_expires_at(now: datetime) -> datetime:
    return now + timedelta(minutes=PICKUP_WINDOW_MINUTES)
