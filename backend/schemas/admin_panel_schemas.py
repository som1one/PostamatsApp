from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from backend.models.enums import LockerCellStatus, LockerStatus


class AdminCreateCityPayload(BaseModel):
    name: str = Field(..., min_length=1, description="City display name")
    slug: str = Field(..., min_length=1, description="City URL slug")
    timezone: str = Field(default="Europe/Minsk", min_length=1, description="City timezone")
    isActive: bool = Field(default=True, description="City active flag")
    sortOrder: int = Field(default=0, description="City sort order")


class AdminUpdateCityPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    slug: str | None = Field(default=None, min_length=1)
    timezone: str | None = Field(default=None, min_length=1)
    isActive: bool | None = None
    sortOrder: int | None = None


class AdminRejectVerificationPayload(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000, description="Причина отклонения для пользователя")


class AdminBlockUserPayload(BaseModel):
    reason: str | None = Field(default=None, max_length=500, description="Причина блокировки")


class AdminCreateLockerPayload(BaseModel):
    cityId: UUID = Field(..., description="Parent city id")
    name: str = Field(..., min_length=1, description="Locker display name")
    address: str = Field(..., min_length=1, description="Locker address")
    status: LockerStatus = Field(default=LockerStatus.ONLINE, description="Locker status")
    partnerName: str | None = Field(default=None, description="Partner label")
    externalLockerId: str | None = Field(default=None, description="External locker identifier")
    externalProvider: str | None = Field(default=None, description="Integration provider code")
    lat: float | None = Field(default=None, description="Latitude")
    lon: float | None = Field(default=None, description="Longitude")
    workingHours: dict[str, Any] | None = Field(default=None, description="Working hours JSON")


class AdminUpdateLockerPayload(BaseModel):
    cityId: UUID | None = None
    name: str | None = Field(default=None, min_length=1)
    address: str | None = Field(default=None, min_length=1)
    status: LockerStatus | None = None
    partnerName: str | None = None
    externalLockerId: str | None = None
    externalProvider: str | None = None
    lat: float | None = None
    lon: float | None = None
    workingHours: dict[str, Any] | None = None


class AdminOpenCellPayload(BaseModel):
    cellId: UUID = Field(..., description="Locker cell id")
    note: str | None = Field(default=None, max_length=500)


class AdminCreateLockerCellPayload(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    externalCellId: str | None = Field(default=None, max_length=128)
    size: str | None = Field(default=None, max_length=64)
    supportsReturn: bool = Field(default=True)


class AdminUpdateLockerCellPayload(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    externalCellId: str | None = Field(default=None, max_length=128)
    size: str | None = Field(default=None, max_length=64)
    status: LockerCellStatus | None = None
    supportsReturn: bool | None = None


class AdminCreateProductCategoryPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=200)
    sortOrder: int = Field(default=0)
    isActive: bool = Field(default=True)


class AdminCreateProductPayload(BaseModel):
    categoryId: UUID = Field(..., description="Product category id")
    name: str = Field(..., min_length=1, max_length=500)
    slug: str | None = Field(
        default=None,
        max_length=200,
        description="Латиница и дефисы; если пусто — из названия или автогенерация",
    )
    shortDescription: str | None = None
    fullDescription: str | None = None
    rulesText: str | None = None
    kitDescription: str | None = None
    brand: str | None = Field(default=None, max_length=200)
    isActive: bool = Field(default=True)
    specsJson: dict[str, Any] | None = None
    coverFileId: UUID | None = Field(default=None, description="ID media-файла обложки")
    galleryFileIds: list[UUID] = Field(default_factory=list, description="Упорядоченный список ID галереи")


class AdminUpdateProductPayload(BaseModel):
    categoryId: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=500)
    slug: str | None = Field(default=None, min_length=1, max_length=200)
    shortDescription: str | None = None
    fullDescription: str | None = None
    rulesText: str | None = None
    kitDescription: str | None = None
    brand: str | None = Field(default=None, max_length=200)
    isActive: bool | None = None
    specsJson: dict[str, Any] | None = None
    coverFileId: UUID | None = Field(default=None, description="ID media-файла обложки")
    galleryFileIds: list[UUID] | None = Field(
        default=None,
        description="Упорядоченный список ID галереи. Пустой список очищает галерею",
    )
