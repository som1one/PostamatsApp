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


class ConfirmReservationPayload(BaseModel):
    paymentId: UUID = Field(..., description="Authorized payment UUID")
