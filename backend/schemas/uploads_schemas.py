from pydantic import BaseModel, Field

PRESIGN_KIND_VALUES = frozenset(
    {
        "verification_front",
        "verification_back",
        "verification_selfie",
        "incident_attachment",
        "condition_photo_before",
        "condition_photo_after",
    }
)


class PresignUploadRequest(BaseModel):
    fileName: str = Field(..., min_length=1, max_length=512)
    mimeType: str = Field(..., min_length=1, max_length=128)
    fileSize: int = Field(..., ge=1)
    kind: str = Field(..., min_length=1, max_length=64)
