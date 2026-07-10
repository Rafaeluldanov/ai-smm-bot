"""Тесты сервиса access/refresh-токенов (HMAC-SHA256, без сети/секретов в логах)."""

from datetime import timedelta

from app.config import Settings
from app.core.redaction import redact_sensitive_text
from app.services.auth_token_service import AuthTokenService


def _svc(secret: str = "strong-secret-value-abcdef123456") -> AuthTokenService:
    return AuthTokenService(Settings(_env_file=None, auth_token_secret=secret))


def test_issue_and_verify_access_token() -> None:
    svc = _svc()
    token = svc.issue_access_token(42, [1, 2, 3])
    payload = svc.verify_access_token(token)
    assert payload is not None
    assert payload.user_id == 42
    assert payload.account_ids == [1, 2, 3]
    assert payload.jti and payload.exp > payload.iat


def test_expired_access_token_rejected() -> None:
    svc = _svc()
    token = svc.issue_access_token(1, [], expires_delta=timedelta(seconds=-5))
    assert svc.verify_access_token(token) is None


def test_wrong_secret_rejected() -> None:
    token = _svc("secret-one-abcdefghijklmnop").issue_access_token(1, [])
    assert _svc("secret-two-abcdefghijklmnop").verify_access_token(token) is None


def test_refresh_token_not_accepted_as_access() -> None:
    svc = _svc()
    refresh = svc.issue_refresh_token(1, "sess-1")
    assert svc.verify_access_token(refresh) is None
    access = svc.issue_access_token(1, [])
    assert svc.verify_refresh_token(access) is None


def test_refresh_token_roundtrip() -> None:
    svc = _svc()
    refresh = svc.issue_refresh_token(7, "sess-xyz")
    payload = svc.verify_refresh_token(refresh)
    assert payload is not None
    assert payload.user_id == 7
    assert payload.session_id == "sess-xyz"


def test_malformed_tokens_return_none() -> None:
    svc = _svc()
    for bad in ("", "a", "a.b", "a.b.c", "not-a-token", "x.y.z.w"):
        assert svc.verify_access_token(bad) is None
        assert svc.verify_refresh_token(bad) is None


def test_hash_token_is_stable_and_hex() -> None:
    h1 = AuthTokenService.hash_token("some-token")
    h2 = AuthTokenService.hash_token("some-token")
    assert h1 == h2 and len(h1) == 64
    assert AuthTokenService.hash_token("other") != h1


def test_token_redacted_in_text() -> None:
    svc = _svc()
    token = svc.issue_access_token(1, [])
    text = f"access_token={token} boom"
    assert token not in redact_sensitive_text(text)
