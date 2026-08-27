from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PreauthPayload(BaseModel):
    reservationId: UUID
    paymentMethodId: UUID | None = None
    paymentToken: str | None = None
    returnUrl: str | None = None
    # Сколько бонусов списать в счёт заказа, в минорных единицах (как все
    # суммы в API). Потолок — доля заказа из настроек, проверяется на бэке.
    bonusAmount: int | None = Field(default=None, ge=0)


class YooKassaWebhookBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    event: str | None = None
    object: dict[str, Any] | None = None

    def object_id(self) -> str | None:
        if not self.object:
            return None
        raw = self.object.get("id")
        return str(raw) if raw is not None else None

    def object_status(self) -> str | None:
        if not self.object:
            return None
        raw = self.object.get("status")
        return str(raw) if raw is not None else None
