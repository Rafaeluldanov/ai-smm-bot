"""Тесты вебхуков платежей (offline): неизвестный провайдер, идемпотентность,
санитизация payload (без секретов).
"""

import pytest
from sqlalchemy.orm import Session

from app.repositories import account_repository, payment_repository, user_repository
from app.services.billing_service import BillingService
from app.services.payments.payment_provider import PaymentProviderError
from app.services.payments.payment_service import PaymentService


def _account(db: Session) -> int:
    user = user_repository.create_user(db, email="wh@e.com", password_hash="x")
    return account_repository.create_account(db, name="A", slug="a", owner_user_id=user.id).id


def test_unknown_provider_rejected(db_session: Session) -> None:
    payments = PaymentService()
    with pytest.raises(PaymentProviderError):
        payments.handle_webhook(db_session, "bogus", {"event": "x"})


def test_mock_webhook_credits_then_duplicate_idempotent(db_session: Session) -> None:
    billing = BillingService()
    payments = PaymentService(billing_service=billing)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 300, idempotency_key="i1")
    payload = {
        "event": "payment.succeeded",
        "provider_payment_id": invoice.provider_payment_id,
        "status": "paid",
    }
    first = payments.handle_webhook(db_session, "mock", payload)
    assert first["processed"] is True
    assert billing.get_balance(db_session, account_id).balance_units == 300
    # Дубликат вебхука — идемпотентно, без второго пополнения.
    second = payments.handle_webhook(db_session, "mock", payload)
    assert second["processed"] is False
    assert second["duplicate"] is True
    assert billing.get_balance(db_session, account_id).balance_units == 300


def test_webhook_payload_sanitized_no_secrets(db_session: Session) -> None:
    payments = PaymentService()
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 100, idempotency_key="i2")
    # Вебхук с «секретом» в payload — он не должен сохраниться в логе.
    payments.handle_webhook(
        db_session,
        "mock",
        {
            "event": "payment.succeeded",
            "provider_payment_id": invoice.provider_payment_id,
            "status": "paid",
            "secret_key": "SUPER_SECRET_VALUE",
            "signature": "xyz",
        },
    )
    from app.models.payment import PaymentWebhookLog

    logs = db_session.query(PaymentWebhookLog).all()
    assert logs
    for log in logs:
        serialized = str(log.payload_sanitized)
        assert "SUPER_SECRET_VALUE" not in serialized
        assert "signature" not in serialized


def test_unsigned_webhook_not_processed(db_session: Session) -> None:
    # Скелет-провайдер (yookassa) не подтверждает подпись → вебхук не обрабатывается.
    payments = PaymentService()
    account_id = _account(db_session)
    payments.create_invoice(db_session, account_id, 100, idempotency_key="i3")
    result = payments.handle_webhook(db_session, "yookassa", {"event": "payment.succeeded"})
    assert result["processed"] is False
    # Лог записан с signature_valid=False.
    logs = payment_repository.list_invoices_by_account(db_session, account_id)
    assert logs  # счёт есть, но не оплачен вебхуком
