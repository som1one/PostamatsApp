from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EsiWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    eventType: str
    eventId: str
    rentalId: UUID | None = None
    lockerId: UUID | None = None
    cellId: UUID | None = None
