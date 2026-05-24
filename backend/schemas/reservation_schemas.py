from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReservationQuotePayload(BaseModel):
    productId: UUID = Field(..., description="Product UUID")
    lockerId: UUID = Field(..., description="Locker UUID")
    durationType: str = Field("day", description="Duration unit")
    durationValue: int = Field(1, ge=1, description="Duration value")


class CreateReservationPayload(ReservationQuotePayload):
    # Окно жизни брони от создания до оплаты (в минутах). По умолчанию 120.
    # Поле оставлено для обратной совместимости; фронт его больше не передаёт.
    pickupWindowMinutes: int = Field(120, ge=1, description="Pickup window in minutes")
    sourceReservationId: UUID | None = Field(
        None,
        description="Existing reservation UUID when user is rescheduling their own booking",
    )
    # Дата/время, на которое пользователь оформил выдачу. Фронт передаёт
    # выбранный chip из DateTimeSelector. Если не передано, считаем "сейчас".
    startAt: datetime | None = Field(
        None,
        description="Pickup start datetime (ISO-8601). Until that moment cell can't be opened.",
    )


class ConfirmReservationPayload(BaseModel):
    # Опциональное: при отсутствии PaymentId аренда создаётся без обязательной
    # привязки к авторизованному платежу (используется в режиме "оплата отключена").
    paymentId: UUID | None = Field(
        None, description="Authorized payment UUID (optional)"
    )
    # Передаётся фронтом ещё раз при подтверждении, чтобы зафиксировать
    # выбранную дату выдачи в `Rental.starts_at`. Если pусто — берём время
    # подтверждения как старт.
    startAt: datetime | None = Field(
        None,
        description="Pickup start datetime (ISO-8601), should match the one passed to /reservations.",
    )
