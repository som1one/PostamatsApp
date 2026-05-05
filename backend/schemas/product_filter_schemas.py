from uuid import UUID

from pydantic import BaseModel, Field


class ProductFilterPricePlanPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    durationType: str = Field(..., min_length=1, max_length=32)
    durationValue: int = Field(..., ge=1)
    baseAmount: int = Field(..., ge=0, description="Minor currency units")
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    isActive: bool = Field(default=True)
    sortOrder: int = Field(default=0)


class AdminCreateProductFilterPayload(BaseModel):
    productId: UUID
    name: str | None = Field(default=None, max_length=500)
    shortDescription: str | None = None
    fullDescription: str | None = None
    rulesText: str | None = None
    kitDescription: str | None = None
    coverUrl: str | None = Field(default=None, max_length=2048)
    galleryUrls: list[str] = Field(default_factory=list)
    tariffs: list[ProductFilterPricePlanPayload] = Field(default_factory=list)
    isActive: bool = Field(default=True)


class AdminUpdateProductFilterPayload(BaseModel):
    name: str | None = Field(default=None, max_length=500)
    shortDescription: str | None = None
    fullDescription: str | None = None
    rulesText: str | None = None
    kitDescription: str | None = None
    coverUrl: str | None = Field(default=None, max_length=2048)
    galleryUrls: list[str] | None = None
    tariffs: list[ProductFilterPricePlanPayload] | None = None
    isActive: bool | None = None
