"""Сервис access/refresh-токенов (JWT-подобный HMAC-SHA256, без внешних зависимостей).

Формат токена — ``header.payload.signature`` (base64url без паддинга), подпись
HMAC-SHA256 секретом ``AUTH_TOKEN_SECRET`` (в production обязателен и надёжен).
Проверка — постоянного времени (``compare_digest``), с валидацией ``exp`` и ``typ``.
Некорректный/просроченный/подделанный токен → ``None`` (исключения наружу не летят).
Токены НИКОГДА не логируются.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import timedelta

from app.config import Settings, get_settings

_ALG = "HS256"
_HEADER = {"alg": _ALG, "typ": "JWT"}
TYP_ACCESS = "access"
TYP_REFRESH = "refresh"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


@dataclass(frozen=True)
class AuthTokenPayload:
    """Полезная нагрузка access-токена."""

    user_id: int
    account_ids: list[int] = field(default_factory=list)
    jti: str = ""
    exp: int = 0
    iat: int = 0


@dataclass(frozen=True)
class RefreshTokenPayload:
    """Полезная нагрузка refresh-токена."""

    user_id: int
    session_id: str
    jti: str = ""
    exp: int = 0
    iat: int = 0


class AuthTokenService:
    """Выпуск и проверка access/refresh-токенов (HMAC-SHA256)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def _secret(self) -> bytes:
        return self._settings.auth_token_secret_effective.encode("utf-8")

    # --- Низкоуровневое кодирование/подпись --------------------------------- #

    def _sign(self, signing_input: str) -> str:
        digest = hmac.new(self._secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        return _b64url_encode(digest)

    def _encode(self, payload: dict[str, object]) -> str:
        header_b64 = _b64url_encode(json.dumps(_HEADER, separators=(",", ":")).encode("utf-8"))
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}"
        return f"{signing_input}.{self._sign(signing_input)}"

    def _decode(self, token: str, expected_typ: str) -> dict[str, object] | None:
        if not token or token.count(".") != 2:
            return None
        header_b64, payload_b64, sig = token.split(".")
        expected_sig = self._sign(f"{header_b64}.{payload_b64}")
        if not hmac.compare_digest(sig, expected_sig):
            return None
        try:
            payload = json.loads(_b64url_decode(payload_b64))
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("typ") != expected_typ:
            return None
        exp = payload.get("exp")
        if not isinstance(exp, int) or exp < int(time.time()):
            return None
        return payload

    # --- Access ------------------------------------------------------------- #

    def issue_access_token(
        self, user_id: int, account_ids: list[int], expires_delta: timedelta | None = None
    ) -> str:
        """Выпустить access-токен (по умолчанию ``AUTH_ACCESS_TOKEN_EXPIRE_MINUTES``)."""
        now = int(time.time())
        ttl = expires_delta or timedelta(minutes=self._settings.auth_access_token_expire_minutes)
        payload: dict[str, object] = {
            "sub": int(user_id),
            "typ": TYP_ACCESS,
            "iat": now,
            "exp": now + int(ttl.total_seconds()),
            "jti": secrets.token_hex(8),
            "account_ids": [int(a) for a in (account_ids or [])],
        }
        return self._encode(payload)

    @staticmethod
    def _as_int(value: object, default: int = 0) -> int:
        return value if isinstance(value, int) else default

    def verify_access_token(self, token: str) -> AuthTokenPayload | None:
        """Проверить access-токен и вернуть payload или ``None``."""
        payload = self._decode(token, TYP_ACCESS)
        if payload is None:
            return None
        sub = payload.get("sub")
        if not isinstance(sub, int):
            return None
        account_ids_raw = payload.get("account_ids")
        account_ids = (
            [int(a) for a in account_ids_raw if isinstance(a, int)]
            if isinstance(account_ids_raw, list)
            else []
        )
        jti = payload.get("jti")
        return AuthTokenPayload(
            user_id=sub,
            account_ids=account_ids,
            jti=jti if isinstance(jti, str) else "",
            exp=self._as_int(payload.get("exp")),
            iat=self._as_int(payload.get("iat")),
        )

    # --- Refresh ------------------------------------------------------------ #

    def issue_refresh_token(
        self, user_id: int, session_id: str, expires_delta: timedelta | None = None
    ) -> str:
        """Выпустить refresh-токен, привязанный к сессии (``sid``)."""
        now = int(time.time())
        ttl = expires_delta or timedelta(days=self._settings.auth_refresh_token_expire_days)
        payload: dict[str, object] = {
            "sub": int(user_id),
            "typ": TYP_REFRESH,
            "iat": now,
            "exp": now + int(ttl.total_seconds()),
            "jti": secrets.token_hex(8),
            "sid": session_id,
        }
        return self._encode(payload)

    def verify_refresh_token(self, token: str) -> RefreshTokenPayload | None:
        """Проверить refresh-токен и вернуть payload или ``None``."""
        payload = self._decode(token, TYP_REFRESH)
        if payload is None:
            return None
        sub = payload.get("sub")
        sid = payload.get("sid")
        if not isinstance(sub, int) or not isinstance(sid, str) or not sid:
            return None
        jti = payload.get("jti")
        return RefreshTokenPayload(
            user_id=sub,
            session_id=sid,
            jti=jti if isinstance(jti, str) else "",
            exp=self._as_int(payload.get("exp")),
            iat=self._as_int(payload.get("iat")),
        )

    # --- Хеш для хранения refresh/session токена ---------------------------- #

    @staticmethod
    def hash_token(token: str) -> str:
        """SHA-256-хеш токена для хранения (в БД хранится только хеш, не токен)."""
        return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def get_auth_token_service() -> AuthTokenService:
    """DI-фабрика сервиса токенов."""
    return AuthTokenService()
