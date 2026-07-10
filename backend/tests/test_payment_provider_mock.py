"""Тесты mock-провайдера платежей (offline): счёт, оплата, идемпотентность."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import account_repository, user_repository
from app.services.billing_service import BillingService
from app.services.payments.payment_provider import PaymentProviderError
from app.services.payments.payment_service import PaymentService


def _account(db: Session) -> int:
    user = user_repository.create_user(db, email="pay@e.com", password_hash="x")
    return account_repository.create_account(db, name="A", slug="a", owner_user_id=user.id).id


def test_create_invoice_does_not_change_balance(db_session: Session) -> None:
    billing = BillingService()
    payments = PaymentService(billing_service=billing)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 500, method="sbp")
    assert invoice.provider == "mock"
    assert invoice.status == "pending"
    assert invoice.amount_units == 500
    assert invoice.payment_url and invoice.payment_url.startswith("/ui/billing/mock-pay/")
    assert invoice.qr_payload  # для sbp/qr есть QR
    # Счёт не меняет баланс.
    assert billing.get_balance(db_session, account_id).balance_units == 0


def test_mock_pay_credits_balance_once(db_session: Session) -> None:
    billing = BillingService()
    payments = PaymentService(billing_service=billing)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 500, idempotency_key="i1")
    payments.mock_pay(db_session, invoice.id)
    assert billing.get_balance(db_session, account_id).balance_units == 500
    # Повторная оплата не пополняет второй раз.
    payments.mock_pay(db_session, invoice.id)
    assert billing.get_balance(db_session, account_id).balance_units == 500


def test_invoice_idempotency_key_returns_same(db_session: Session) -> None:
    payments = PaymentService()
    account_id = _account(db_session)
    a = payments.create_invoice(db_session, account_id, 100, idempotency_key="dup")
    b = payments.create_invoice(db_session, account_id, 100, idempotency_key="dup")
    assert a.id == b.id


def test_real_provider_disabled_without_live(db_session: Session) -> None:
    payments = PaymentService()
    account_id = _account(db_session)
    with pytest.raises(PaymentProviderError):
        payments.create_invoice(db_session, account_id, 100, provider="yookassa")


def test_amount_rub_conversion(db_session: Session) -> None:
    payments = PaymentService()
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 1000)
    assert invoice.amount_rub >= 1  # units → рубли по ориентировочной цене
