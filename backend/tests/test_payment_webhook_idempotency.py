"""Тесты идемпотентности и безопасности вебхуков платежей (offline).

- дубликат события (provider_event_id) игнорируется;
- дубликат оплаты не пополняет второй раз;
- недоверенная подпись в production отклоняется (403);
- payload санитизируется (без секретов), статус журналируется.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_payment_service
from app.config import Settings
from app.main import app
from app.models.payment import PaymentWebhookLog
from app.repositories import account_repository, user_repository
from app.services.billing_service import BillingService
from app.services.payments.payment_provider import WebhookSignatureError
from app.services.payments.payment_service import PaymentService


def _account(db: Session, email: str = "wh@e.com") -> int:
    user = user_repository.create_user(db, email=email, password_hash="x")
    return account_repository.create_account(db, name="A", slug="a", owner_user_id=user.id).id


def _paid_payload(invoice, event_id: str) -> dict:  # noqa: ANN001
    return {
        "event": "payment.succeeded",
        "event_id": event_id,
        "provider_payment_id": invoice.provider_payment_id,
        "status": "paid",
    }


def test_duplicate_event_id_ignored(db_session: Session) -> None:
    billing = BillingService()
    payments = PaymentService(billing_service=billing)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 300, idempotency_key="i1")
    payload = _paid_payload(invoice, "evt-1")
    first = payments.handle_webhook(db_session, "mock", payload)
    assert first["processed"] is True
    assert billing.get_balance(db_session, account_id).balance_units == 300
    # То же событие (тот же event_id) — игнор, без второго пополнения.
    second = payments.handle_webhook(db_session, "mock", payload)
    assert second["processed"] is False
    assert second["duplicate"] is True
    assert billing.get_balance(db_session, account_id).balance_units == 300
    # В журнале есть запись со статусом ignored.
    statuses = {log.status for log in db_session.query(PaymentWebhookLog).all()}
    assert "processed" in statuses
    assert "ignored" in statuses


def test_duplicate_paid_no_double_credit_without_event_id(db_session: Session) -> None:
    billing = BillingService()
    payments = PaymentService(billing_service=billing)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 200, idempotency_key="i2")
    payload = {
        "event": "payment.succeeded",
        "provider_payment_id": invoice.provider_payment_id,
        "status": "paid",
    }
    payments.handle_webhook(db_session, "mock", payload)
    payments.handle_webhook(db_session, "mock", payload)
    assert billing.get_balance(db_session, account_id).balance_units == 200


def test_invalid_signature_rejected_in_production(db_session: Session) -> None:
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
    )
    payments = PaymentService(settings=prod)
    with pytest.raises(WebhookSignatureError):
        payments.handle_webhook(db_session, "yookassa", {"event": "payment.succeeded"})


def test_invalid_signature_http_403_in_production(client: TestClient) -> None:
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
    )
    app.dependency_overrides[get_payment_service] = lambda: PaymentService(settings=prod)
    try:
        r = client.post("/billing/webhooks/yookassa", json={"event": "payment.succeeded"})
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_payment_service, None)


def test_local_invalid_signature_not_processed(db_session: Session) -> None:
    # В local недоверенный вебхук не роняет запрос, но и не пополняет.
    payments = PaymentService()
    account_id = _account(db_session)
    payments.create_invoice(db_session, account_id, 100, provider=None, idempotency_key="i3")
    result = payments.handle_webhook(db_session, "yookassa", {"event": "payment.succeeded"})
    assert result["processed"] is False


def test_webhook_payload_sanitized_no_secret(db_session: Session) -> None:
    payments = PaymentService()
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 100, idempotency_key="i4")
    payments.handle_webhook(
        db_session,
        "mock",
        {
            "event": "payment.succeeded",
            "event_id": "evt-secret",
            "provider_payment_id": invoice.provider_payment_id,
            "status": "paid",
            "secret_key": "SUPER_SECRET_VALUE",
            "signature": "xyz",
        },
    )
    for log in db_session.query(PaymentWebhookLog).all():
        serialized = str(log.payload_sanitized)
        assert "SUPER_SECRET_VALUE" not in serialized
        assert "signature" not in serialized
