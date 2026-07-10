"""Pydantic-схемы аутентификации и аккаунтов SaaS-платформы."""

from datetime import datetime

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
    """Результат регистрации/входа: access-токен + пользователь + его аккаунты.

    ``token`` == ``access_token`` (для обратной совместимости с прежним UI/тестами).
    Refresh-токен ставится cookie'й; ``csrf_token`` — если CSRF включён.
    """

    token: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 0
    csrf_token: str | None = None
    user: UserRead
    accounts: list[AccountRead] = Field(default_factory=list)


class RefreshResult(BaseModel):
    """Результат ротации: новый access-токен."""

    token: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 0
    csrf_token: str | None = None


class LogoutResult(BaseModel):
    """Результат logout / logout-all."""

    status: str = "ok"
    revoked_sessions: int = 0


class AuthSessionRead(BaseModel):
    """Активная сессия пользователя (без хеша refresh-токена)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    user_agent: str | None = None
    ip_address: str | None = None
    status: str
    last_seen_at: datetime | None = None
    expires_at: datetime
    created_at: datetime


class MeResponse(BaseModel):
    """Текущий пользователь и его аккаунты (GET /auth/me)."""

    user: UserRead
    accounts: list[AccountRead] = Field(default_factory=list)
