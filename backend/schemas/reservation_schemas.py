from uuid import UUID

from pydantic import BaseModel, Field


class ReservationQuotePayload(BaseModel):
    productId: UUID = Field(..., description="Product UUID")
    lockerId: UUID = Field(..., description="Locker UUID")
    durationType: str = Field("day", description="Duration unit")
    durationValue: int = Field(1, ge=1, description="Duration value")


class CreateReservationPayload(ReservationQuotePayload):
    pickupWindowMinutes: int = Field(..., ge=1, description="Pickup window in minutes")
    sourceReservationId: UUID | None = Field(
        None,
        description="Existing reservation UUID when user is rescheduling their own booking",
    )


class ConfirmReservationPayload(BaseModel):
    paymentId: UUID = Field(..., description="Authorized payment UUID")
