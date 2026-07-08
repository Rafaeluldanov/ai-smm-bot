"""Сервис аутентификации и провижининга аккаунтов SaaS-платформы.

Регистрация создаёт пользователя, его аккаунт (workspace) и членство владельца.
Пароли хешируются PBKDF2 (см. :mod:`app.core.security`); сырой пароль не хранится
и не логируется. Токен — подписанная dev-заглушка (не продакшн-JWT).
"""

import re

from sqlalchemy.orm import Session

from app.core.security import PasswordHasher, make_dev_token
from app.models.account import Account
from app.models.user import User
from app.repositories import account_repository, user_repository

_MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    """Базовая ошибка аутентификации/регистрации (API → 400/401)."""


class EmailAlreadyExistsError(AuthError):
    """Пользователь с таким email уже существует (API → 409)."""

    def __init__(self, email: str) -> None:
        super().__init__(f"Пользователь с email '{email}' уже существует")


class InvalidCredentialsError(AuthError):
    """Неверный email или пароль (API → 401)."""

    def __init__(self) -> None:
        super().__init__("Неверный email или пароль")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "workspace"


class AuthService:
    """Регистрация, вход, провижининг аккаунтов и dev-токены."""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()

    # --- Регистрация / вход ---

    def register_user(
        self,
        db: Session,
        email: str,
        password: str,
        full_name: str | None = None,
        account_name: str | None = None,
    ) -> tuple[User, Account]:
        """Зарегистрировать пользователя и создать его первый аккаунт."""
        email_norm = email.strip().lower()
        if "@" not in email_norm or "." not in email_norm.split("@")[-1]:
            raise AuthError("Некорректный email")
        if len(password) < _MIN_PASSWORD_LENGTH:
            raise AuthError(f"Пароль должен быть не короче {_MIN_PASSWORD_LENGTH} символов")
        if user_repository.get_user_by_email(db, email_norm) is not None:
            raise EmailAlreadyExistsError(email_norm)

        user = user_repository.create_user(db, email_norm, self._hasher.hash(password), full_name)
        account = self.create_account_for_user(
            db, user, account_name or (full_name or email_norm.split("@")[0])
        )
        return user, account

    def authenticate_user(self, db: Session, email: str, password: str) -> User:
        """Проверить учётные данные и вернуть пользователя. Иначе InvalidCredentialsError."""
        user = user_repository.get_user_by_email(db, email)
        if (
            user is None
            or not user.is_active
            or not self._hasher.verify(password, user.password_hash)
        ):
            raise InvalidCredentialsError()
        return user

    # --- Аккаунты ---

    def create_account_for_user(
        self, db: Session, user: User, account_name: str, role: str = "owner"
    ) -> Account:
        """Создать аккаунт с уникальным slug и членством владельца."""
        slug = self._unique_slug(db, _slugify(account_name))
        account = account_repository.create_account(db, account_name, slug, user.id)
        account_repository.create_membership(db, account.id, user.id, role=role)
        return account

    def list_user_accounts(self, db: Session, user_id: int) -> list[Account]:
        """Вернуть аккаунты пользователя (по членствам)."""
        return account_repository.list_accounts_for_user(db, user_id)

    def get_current_account(
        self, db: Session, user_id: int, account_id: int | None = None
    ) -> Account | None:
        """Placeholder для будущей auth-middleware: текущий аккаунт пользователя.

        Если ``account_id`` задан — вернуть его, только если пользователь состоит в
        аккаунте; иначе — первый аккаунт пользователя (или None).
        """
        accounts = self.list_user_accounts(db, user_id)
        if account_id is not None:
            return next((a for a in accounts if a.id == account_id), None)
        return accounts[0] if accounts else None

    def issue_token(self, user: User) -> str:
        """Выдать подписанный dev-токен сессии (не продакшн-JWT)."""
        return make_dev_token(user.id)

    def _unique_slug(self, db: Session, base: str) -> str:
        slug = base
        suffix = 2
        while account_repository.get_account_by_slug(db, slug) is not None:
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug
