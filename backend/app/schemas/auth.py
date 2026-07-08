"""Pydantic-схемы аутентификации и аккаунтов SaaS-платформы."""

from pydantic import BaseModel, ConfigDict, Field


class UserRegisterRequest(BaseModel):
    """Регистрация пользователя (создаёт user + account + membership)."""

    email: str
    password: str = Field(min_length=8)
    full_name: str | None = None
    account_name: str | None = None


class UserLoginRequest(BaseModel):
    """Вход по email/паролю."""

    email: str
    password: str


class UserRead(BaseModel):
    """Пользователь в ответах API (без password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str | None = None
    is_active: bool
    is_superuser: bool


class AccountRead(BaseModel):
    """Аккаунт/воркспейс в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    owner_user_id: int
    status: str


class AuthResult(BaseModel):
    """Результат регистрации/входа: dev-токен + пользователь + его аккаунты."""

    token: str
    token_type: str = "dev"
    user: UserRead
    accounts: list[AccountRead] = Field(default_factory=list)


class MeResponse(BaseModel):
    """Текущий пользователь и его аккаунты (GET /auth/me)."""

    user: UserRead
    accounts: list[AccountRead] = Field(default_factory=list)
