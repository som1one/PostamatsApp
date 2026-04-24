from pydantic import BaseModel, Field


class AdminLoginPayload(BaseModel):
    login: str = Field(..., min_length=1, description="Admin login")
    password: str = Field(..., min_length=1, description="Admin password")
