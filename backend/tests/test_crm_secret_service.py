"""Тесты сервисного слоя секретов CRM-ресурсов."""

from app.services.crm_secret_service import (
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
    mask_secret,
)


def test_encrypt_decrypt_round_trip() -> None:
    secret = "super-secret-token-123"
    stored = encrypt_secret(secret)
    assert stored != secret
    assert secret not in stored
    assert is_encrypted(stored)
    assert decrypt_secret(stored) == secret


def test_mask_hides_value() -> None:
    masked = mask_secret("super-secret-token-123")
    assert masked.startswith("•")
    assert "super-secret" not in masked
    assert masked.endswith("-123")


def test_mask_short_secret_fully_masked() -> None:
    assert mask_secret("abc") == "••••"
    assert mask_secret("") == ""


def test_is_encrypted_false_for_plain() -> None:
    assert not is_encrypted(None)
    assert not is_encrypted("plain")
