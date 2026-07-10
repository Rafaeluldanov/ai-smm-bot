"""Сервис серверных сессий: логин-сессия, ротация refresh, logout / logout-all.

Логин создаёт сессию (в БД — только хеш refresh-токена) и выдаёт access+refresh+csrf.
Refresh ротирует токен (защита от повторного использования); logout ревокирует сессию.
Токены не логируются.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.auth_session import AuthSession
from app.models.user import User
from app.repositories import account_repository, auth_session_repository
from app.services.auth_token_service import AuthTokenService


class AuthSessionError(Exception):
    """Ошибка сессии (невалидный/отозванный/просроченный refresh-токен)."""


@dataclass(frozen=True)
class SessionTokens:
    """Результат логина/refresh: access + refresh + csrf + сессия."""

    access_token: str
    refresh_token: str
    csrf_token: str
    session: AuthSession
    expires_in: int


class AuthSessionService:
    """Управление серверными сессиями поверх ``AuthTokenService``."""

    def __init__(
        self, settings: Settings | None = None, token_service: AuthTokenService | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._tokens = token_service or AuthTokenService(self._settings)

    def _account_ids(self, db: Session, user_id: int) -> list[int]:
        return [a.id for a in account_repository.list_accounts_for_user(db, user_id)]

    def _access_ttl_seconds(self) -> int:
        return self._settings.auth_access_token_expire_minutes * 60

    def create_login_session(
        self,
        db: Session,
        user: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionTokens:
        """Создать сессию входа и выдать access/refresh/csrf-токены."""
        now = datetime.now(UTC)
        session_id = secrets.token_urlsafe(24)
        refresh_token = self._tokens.issue_refresh_token(user.id, session_id)
        access_token = self._tokens.issue_access_token(user.id, self._account_ids(db, user.id))
        csrf_token = secrets.token_urlsafe(24)
        expires_at = now + timedelta(days=self._settings.auth_refresh_token_expire_days)
        session = auth_session_repository.create_session(
            db,
            user_id=user.id,
            session_id=session_id,
            refresh_token_hash=AuthTokenService.hash_token(refresh_token),
            user_agent=(user_agent or "")[:512] or None,
            ip_address=ip_address,
            status="active",
            last_seen_at=now,
            expires_at=expires_at,
            session_metadata={},
        )
        return SessionTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            csrf_token=csrf_token,
            session=session,
            expires_in=self._access_ttl_seconds(),
        )

    def refresh_session(self, db: Session, refresh_token: str) -> SessionTokens:
        """Проверить refresh-токен, ротировать его и выдать новый access."""
        payload = self._tokens.verify_refresh_token(refresh_token or "")
        if payload is None:
            raise AuthSessionError("Невалидный или просроченный refresh-токен")
        session = auth_session_repository.get_by_session_id(db, payload.session_id)
        now = datetime.now(UTC)
        if session is None or session.status != "active":
            raise AuthSessionError("Сессия не найдена или отозвана")
        if session.expires_at is not None and _aware(session.expires_at) < now:
            auth_session_repository.revoke_session(db, session, now)
            raise AuthSessionError("Сессия истекла")
        # Защита от повторного использования: хеш должен совпасть с текущим в БД.
        if not secrets.compare_digest(
            AuthTokenService.hash_token(refresh_token), session.refresh_token_hash
        ):
            auth_session_repository.revoke_session(db, session, now)
            raise AuthSessionError("Refresh-токен уже использован — сессия отозвана")
        user = db.get(User, session.user_id)
        if user is None or not user.is_active:
            raise AuthSessionError("Пользователь недоступен")
        # Ротация: новый refresh + новый access, обновляем хеш и last_seen.
        new_refresh = self._tokens.issue_refresh_token(user.id, session.session_id)
        auth_session_repository.replace_refresh_hash(
            db, session, AuthTokenService.hash_token(new_refresh)
        )
        auth_session_repository.update_last_seen(db, session, now)
        access_token = self._tokens.issue_access_token(user.id, self._account_ids(db, user.id))
        return SessionTokens(
            access_token=access_token,
            refresh_token=new_refresh,
            csrf_token=secrets.token_urlsafe(24),
            session=session,
            expires_in=self._access_ttl_seconds(),
        )

    def refresh_identity(self, refresh_token: str) -> tuple[int, str] | None:
        """Вернуть (user_id, session_id) из refresh-токена без ротации, или None."""
        payload = self._tokens.verify_refresh_token(refresh_token or "")
        if payload is None:
            return None
        return payload.user_id, payload.session_id

    def logout_session(self, db: Session, session_id: str) -> bool:
        """Ревокировать сессию по session_id. True — если была активна."""
        session = auth_session_repository.get_by_session_id(db, session_id)
        if session is None or session.status != "active":
            return False
        auth_session_repository.revoke_session(db, session, datetime.now(UTC))
        return True

    def logout_all(self, db: Session, user_id: int) -> int:
        """Ревокировать все активные сессии пользователя. Возвращает число."""
        return auth_session_repository.revoke_all_user_sessions(db, user_id, datetime.now(UTC))

    def list_sessions(self, db: Session, user_id: int) -> list[AuthSession]:
        """Активные сессии пользователя (без хешей токенов в ответе — см. схему)."""
        return auth_session_repository.list_active_for_user(db, user_id)

    def touch_last_seen(self, db: Session, session_id: str) -> None:
        """Обновить last_seen активной сессии (best-effort, без ошибок наружу)."""
        session = auth_session_repository.get_by_session_id(db, session_id)
        if session is not None and session.status == "active":
            auth_session_repository.update_last_seen(db, session, datetime.now(UTC))


def _aware(dt: datetime) -> datetime:
    """Привести datetime к tz-aware (SQLite возвращает naive)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def get_auth_session_service() -> AuthSessionService:
    """DI-фабрика сервиса сессий."""
    return AuthSessionService()
