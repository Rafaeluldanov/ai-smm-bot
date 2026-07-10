"""Тесты редакции секретов (core/redaction): токены/ключи/пароли не утекают."""

from app.core.redaction import redact_sensitive_text, sanitize_metadata


def test_redact_vk_token() -> None:
    out = redact_sensitive_text("token is vk1.abcDEF1234567890 done")
    assert "vk1.abcDEF1234567890" not in out
    assert "***" in out


def test_redact_meta_token() -> None:
    out = redact_sensitive_text("EAAGabcдangling EAAGm0123456789ABCDEF")
    assert "EAAGm0123456789ABCDEF" not in out


def test_redact_telegram_bot_token() -> None:
    out = redact_sensitive_text("bot 123456789:AAEjKL-mnop_QRstuvwx0123456789ABCDE ok")
    assert "AAEjKL-mnop_QRstuvwx0123456789ABCDE" not in out
    assert "***" in out


def test_redact_access_token_query_param() -> None:
    out = redact_sensitive_text("https://api/x?access_token=SECRETVALUE123&y=1")
    assert "SECRETVALUE123" not in out


def test_redact_authorization_bearer() -> None:
    out = redact_sensitive_text("Authorization: Bearer abc.def.ghi")
    assert "abc.def.ghi" not in out
    assert "***" in out


def test_redact_key_value_secrets() -> None:
    for text in (
        "app_secret=TOPSECRET",
        "password=hunter2",
        "api_key=KKKK1234",
        "client_secret=zzz999",
        "webhook_secret=whsec_abcdef",
    ):
        out = redact_sensitive_text(text)
        assert "***" in out
        assert text.split("=", 1)[1] not in out


def test_sanitize_metadata_drops_sensitive_keys() -> None:
    meta = {
        "amount": 100,
        "access_token": "vk1.SECRET",
        "api_key": "KKK",
        "password": "p",
        "authorization": "Bearer x",
        "nested": {"secret": "s", "ok": "value", "note": "access_token=INLINE"},
        "list": ["clean", "token=INLINE2"],
    }
    clean = sanitize_metadata(meta)
    assert clean["amount"] == 100
    assert "access_token" not in clean
    assert "api_key" not in clean
    assert "password" not in clean
    assert "authorization" not in clean
    assert "secret" not in clean["nested"]
    assert clean["nested"]["ok"] == "value"
    # Inline-секреты в строковых значениях тоже замазаны.
    assert "INLINE" not in clean["nested"]["note"]
    assert "INLINE2" not in clean["list"][1]


def test_sanitize_metadata_handles_none_and_scalars() -> None:
    # Скаляры/None проходят как есть (нормализацию к {} делает AuditLogService).
    assert sanitize_metadata(None) is None
    assert sanitize_metadata({}) == {}
    assert sanitize_metadata(42) == 42
