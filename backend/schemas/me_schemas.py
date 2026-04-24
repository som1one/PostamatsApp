from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from backend.models.enums import DocumentType


class RentalReturnRequestPayload(BaseModel):
    """Тело для запроса возврата. lockerId — если возврат в другой постамат; иначе используется точка выдачи."""

    lockerId: UUID | None = Field(default=None, description="Постамат для возврата")


class UpdateMePayload(BaseModel):
    firstName: str | None = Field(None, description="First name")
    lastName: str | None = Field(None, description="Last name")
    middleName: str | None = Field(None, description="Middle name")
    birthDate: date | None = Field(None, description="Birth date")
    preferredCityId: UUID | None = Field(None, description="Preferred city ID")
    email: str | None = Field(None, description="Email")


VerificationFileKind = Literal["document_front", "document_back", "selfie"]


class VerificationFilePayload(BaseModel):
    fileKey: str = Field(..., description="Storage file key from presign upload")
    kind: VerificationFileKind = Field(..., description="document_front | document_back | selfie")


class CreateVerificationRequest(BaseModel):
    firstName: str = Field(..., description="First name")
    lastName: str = Field(..., description="Last name")
    birthDate: date = Field(..., description="Birth date")
    documentType: DocumentType = Field(..., description="Document type")
    documentNumber: str = Field(..., description="Document number")
    documentIssueDate: date | None = Field(None, description="Document issue date")
    documentExpiryDate: date | None = Field(None, description="Document expiry date")
    files: list[VerificationFilePayload] = Field(
        ...,
        min_length=1,
        description="Uploaded verification files (front + selfie required)",
    )
