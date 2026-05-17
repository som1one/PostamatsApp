from pydantic import BaseModel, ConfigDict


class EsiWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    eventType: str
    eventId: str
    rentalId: str | None = None
    lockerId: str | None = None
    lockerExternalId: str | None = None
    serial: str | None = None
    machineSerial: str | None = None
    cellId: str | None = None
    cellExternalId: str | None = None
