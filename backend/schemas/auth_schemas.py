from pydantic import BaseModel, Field
from datetime import date
from uuid import UUID

class RequestCodePayload(BaseModel):
    phone: str = Field(..., description="Phone number to request code")


class ConfirmCodePayload(BaseModel):
    verificationSessionId: UUID = Field(..., description="Verification session ID")
    code: str = Field(..., description="Code to confirm")

