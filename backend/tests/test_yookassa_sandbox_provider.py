"""Тесты sandbox-adapter YooKassa (offline): payload, отсутствие сети и секретов."""

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.payments.payment_provider import PaymentProviderError, WebhookSignatureError
from app.services.payments.payment_service import PaymentService
from app.services.payments.yookassa_payment_service import (
    YooKassaPaymentProvider,
    build_yookassa_payment_payload,
    verify_yookassa_signature,
)

_INVOICE = SimpleNamespace(id=42, account_id=7, amount_units=500, amount_rub=500)


def _sandbox_settings(**extra: object) -> Settings:
    return Settings(
        _env_file=None,
        payments_live_enabled=False,
        payments_provider_http_enabled=False,
        yookassa_sandbox_enabled=True,
        **extra,
    )


def test_build_payload_bank_card() -> None:
    payload = build_yookassa_payment_payload(
        _INVOICE, "bank_card", return_url="https://x/ui/billing"
    )
    assert payload["amount"] == {"value": "500.00", "currency": "RUB"}
    assert payload["confirmation"]["type"] == "redirect"
    assert payload["confirmation"]["return_url"] == "https://x/ui/billing"
    assert payload["payment_method_data"]["type"] == "bank_card"
    assert payload["metadata"]["invoice_id"] == 42
    assert payload["metadata"]["amount_units"] == 500


def test_build_payload_sbp() -> None:
    payload = build_yookassa_payment_payload(_INVOICE, "sbp")
    assert payload["payment_method_data"]["type"] == "sbp"


def test_build_payload_qr_maps_to_sbp() -> None:
    payload = build_yookassa_payment_payload(_INVOICE, "qr")
    assert payload["payment_method_data"]["type"] == "sbp"


def test_sandbox_create_invoice_no_http() -> None:
    provider = YooKassaPaymentProvider(_sandbox_settings())
    result = provider.create_invoice(7, 500, 500, "sbp", idempotency_key="k1")
    assert result.provider == "yookassa"
    assert result.status == "pending"
    assert result.sandbox is True
    assert result.provider_payment_id.startswith("yoo_sandbox_")
    assert result.qr_payload  # для sbp есть QR
    # Детерминированность (никакого случайного/сетевого id).
    again = provider.create_invoice(7, 500, 500, "sbp", idempotency_key="k1")
    assert again.provider_payment_id == result.provider_payment_id


def test_http_flag_blocks_real_call() -> None:
    provider = YooKassaPaymentProvider(
        Settings(_env_file=None, yookassa_sandbox_enabled=True, payments_provider_http_enabled=True)
    )
    with pytest.raises(PaymentProviderError):
        provider.create_invoice(7, 500, 500, "bank_card")


def test_sandbox_off_blocks_invoice() -> None:
    provider = YooKassaPaymentProvider(Settings(_env_file=None, yookassa_sandbox_enabled=False))
    with pytest.raises(PaymentProviderError):
        provider.create_invoice(7, 500, 500, "bank_card")


def test_no_secret_leak_in_payload_or_result() -> None:
    settings = _sandbox_settings(
        yookassa_secret_key="SECRET_KEY_VALUE", yookassa_webhook_secret="WHSECRET"
    )
    provider = YooKassaPaymentProvider(settings)
    result = provider.create_invoice(7, 500, 500, "bank_card", customer={"email": "a@e.com"})
    blob = json.dumps(result.metadata) + str(result.payment_url) + str(result.qr_payload)
    assert "SECRET_KEY_VALUE" not in blob
    assert "WHSECRET" not in blob
    payload = build_yookassa_payment_payload(_INVOICE, "bank_card", {"email": "a@e.com"})
    assert "SECRET_KEY_VALUE" not in json.dumps(payload)


def test_webhook_missing_secret_not_trusted() -> None:
    # Без webhook-секрета подпись не подтверждается.
    provider = YooKassaPaymentProvider(_sandbox_settings(yookassa_webhook_secret=""))
    res = provider.handle_webhook(
        {"event": "payment.succeeded", "object": {"id": "p1"}}, headers={}
    )
    assert res.signature_valid is False


def test_production_missing_webhook_secret_blocks_live(db_session) -> None:  # noqa: ANN001
    # В production недоверенный вебхук (нет секрета) → WebhookSignatureError (API 403).
    prod = Settings(
        _env_file=None,
        app_env="production",
        auth_token_secret="prod-strong-secret-value-1234567",
        auth_allow_dev_token=False,
        auth_require_auth=True,
        auth_cookie_secure=True,
        csrf_protection_enabled=True,
        rate_limit_enabled=True,
        yookassa_sandbox_enabled=True,
        yookassa_webhook_secret="",
    )
    payments = PaymentService(settings=prod)
    with pytest.raises(WebhookSignatureError):
        payments.handle_webhook(db_session, "yookassa", {"event": "payment.succeeded"})


def test_valid_signature_accepted() -> None:
    secret = "whsecret123"
    provider = YooKassaPaymentProvider(_sandbox_settings(yookassa_webhook_secret=secret))
    payload = {"event": "payment.succeeded", "object": {"id": "p1", "status": "succeeded"}}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    assert verify_yookassa_signature(payload, {"X-Yookassa-Signature": sig}, secret) is True
    res = provider.handle_webhook(payload, {"X-Yookassa-Signature": sig})
    assert res.signature_valid is True
    assert res.status == "paid"
    assert res.provider_payment_id == "p1"
