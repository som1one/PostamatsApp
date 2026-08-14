import re
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Логин франшизы вводится руками и используется как имя пользователя,
# поэтому оставляем только безопасный набор символов.
LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")

MIN_PASSWORD_LENGTH = 8


def _normalize_login(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not LOGIN_RE.fullmatch(normalized):
        raise ValueError(
            "Логин: 3–64 символа, латиница, цифры и . _ -, начинается с буквы или цифры"
        )
    return normalized


def _validate_password(value: str) -> str:
    password = str(value or "").strip()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    if len(password) > 128:
        raise ValueError("Пароль слишком длинный")
    return password


class AdminCreateFranchisePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Название франшизы")
    login: str = Field(..., description="Логин для входа в админку")
    password: str = Field(..., description="Пароль для входа")
    cityId: UUID = Field(..., description="Город, к которому привязан доступ")

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = str(value or "").strip()
        if not stripped:
            raise ValueError("Название обязательно")
        return stripped

    @field_validator("login")
    @classmethod
    def _check_login(cls, value: str) -> str:
        return _normalize_login(value)

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)


class AdminUpdateFranchisePayload(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    cityId: UUID | None = None
    isActive: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        if not stripped:
            raise ValueError("Название не может быть пустым")
        return stripped


class AdminFranchisePasswordPayload(BaseModel):
    password: str = Field(..., description="Новый пароль")

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)
