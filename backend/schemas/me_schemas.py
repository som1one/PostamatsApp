from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from backend.models.enums import DocumentType

# Держим в синхроне с backend.utils.return_photos.RETURN_PHOTO_NOTE_MAX:
# схемы не импортируют утилиты, чтобы не тянуть модели в pydantic-слой.
_RETURN_PHOTO_NOTE_MAX = 500


class RentalReturnRequestPayload(BaseModel):
    """Тело для запроса возврата. lockerId — если возврат в другой постамат; иначе используется точка выдачи."""

    lockerId: UUID | None = Field(default=None, description="Постамат для возврата")


class RentalConfirmReturnPayload(BaseModel):
    """Тело подтверждения возврата. Необязательное: старые клиенты шлют пустой POST.

    Лимит числа фото проверяет ручка (400 RETURN_PHOTOS_TOO_MANY после дедупа),
    а не схема — иначе клиент получил бы невнятный 422.
    """

    photoFileIds: list[UUID] | None = Field(
        default=None,
        description="fileId из /uploads/presign с kind condition_photo_after, уже залитые PUT-ом",
    )
    note: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, max_length=_RETURN_PHOTO_NOTE_MAX),
    ] = Field(default=None, description="Комментарий клиента к возврату")


class RentalExtendPayload(BaseModel):
    """Тело для продления аренды: выбранный тариф + куда вернуть после оплаты."""

    durationType: str = Field(..., description="Тип длительности тарифа (day/week/…)")
    durationValue: int = Field(..., ge=1, le=365, description="Значение длительности")
    returnUrl: str | None = Field(
        default=None, description="URL возврата из ЮKassa после оплаты"
    )


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
    documentName: str | None = Field(None, description="Custom document name for other type")
    documentNumber: str = Field(..., description="Document number")
    documentIssueDate: date | None = Field(None, description="Document issue date")
    documentExpiryDate: date | None = Field(None, description="Document expiry date")
    files: list[VerificationFilePayload] = Field(
        ...,
        min_length=1,
        description="Uploaded verification files (front + selfie required)",
    )


class DeleteVerificationRequest(BaseModel):
    documentNumber: str = Field(..., description="Document number for exact verification lookup")
