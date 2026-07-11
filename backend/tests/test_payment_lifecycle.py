"""Тесты жизненного цикла счёта (offline): create → pending → paid/failed/canceled/expired.

Ключевые инварианты безопасности:
- создание счёта НЕ пополняет баланс;
- оплата пополняет ровно один раз (идемпотентно);
- failed/canceled/expired НЕ пополняют;
- сумма счёта неизменяема после pending.
"""

import pytest
from sqlalchemy.orm import Session

from app.repositories import account_repository, user_repository
from app.services.billing_service import BillingService
from app.services.payments.payment_provider import (
    TX_STATUS_SUCCEEDED,
    PaymentProviderError,
)
from app.services.payments.payment_service import PaymentService


def _account(db: Session, email: str = "life@e.com") -> int:
    user = user_repository.create_user(db, email=email, password_hash="x")
    return account_repository.create_account(db, name="A", slug="a", owner_user_id=user.id).id


def _svc(db: Session) -> tuple[BillingService, PaymentService]:
    billing = BillingService()
    return billing, PaymentService(billing_service=billing)


def test_invoice_created_pending(db_session: Session) -> None:
    _, payments = _svc(db_session)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 500, method="bank_card")
    assert invoice.status == "pending"
    assert invoice.provider == "mock"


def test_invoice_creation_no_credit(db_session: Session) -> None:
    billing, payments = _svc(db_session)
    account_id = _account(db_session)
    payments.create_invoice(db_session, account_id, 700)
    assert billing.get_balance(db_session, account_id).balance_units == 0


def test_mock_pay_credits_and_writes_transaction(db_session: Session) -> None:
    billing, payments = _svc(db_session)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 500, idempotency_key="p1")
    payments.mock_pay(db_session, invoice.id)
    assert billing.get_balance(db_session, account_id).balance_units == 500
    from app.models.payment import PaymentTransaction

    txs = db_session.query(PaymentTransaction).filter_by(invoice_id=invoice.id).all()
    assert len(txs) == 1
    assert txs[0].status == TX_STATUS_SUCCEEDED


def test_duplicate_mock_pay_no_double_credit(db_session: Session) -> None:
    billing, payments = _svc(db_session)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 500, idempotency_key="p2")
    payments.mock_pay(db_session, invoice.id)
    payments.mock_pay(db_session, invoice.id)
    payments.mock_pay(db_session, invoice.id)
    assert billing.get_balance(db_session, account_id).balance_units == 500


def test_mock_fail_no_credit_idempotent(db_session: Session) -> None:
    billing, payments = _svc(db_session)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 500, idempotency_key="f1")
    r1 = payments.mock_fail(db_session, invoice.id)
    assert r1.status == "failed"
    # Идемпотентно.
    r2 = payments.mock_fail(db_session, invoice.id)
    assert r2.status == "failed"
    assert billing.get_balance(db_session, account_id).balance_units == 0


def test_mock_cancel_no_credit(db_session: Session) -> None:
    billing, payments = _svc(db_session)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 400, idempotency_key="c1")
    assert payments.mock_cancel(db_session, invoice.id).status == "canceled"
    assert billing.get_balance(db_session, account_id).balance_units == 0


def test_mock_expire_no_credit(db_session: Session) -> None:
    billing, payments = _svc(db_session)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 400, idempotency_key="e1")
    assert payments.mock_expire(db_session, invoice.id).status == "expired"
    assert billing.get_balance(db_session, account_id).balance_units == 0


def test_cannot_fail_paid_invoice(db_session: Session) -> None:
    _, payments = _svc(db_session)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 500, idempotency_key="pf")
    payments.mock_pay(db_session, invoice.id)
    with pytest.raises(PaymentProviderError):
        payments.mock_cancel(db_session, invoice.id)


def test_cannot_pay_failed_invoice(db_session: Session) -> None:
    billing, payments = _svc(db_session)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 500, idempotency_key="ff")
    payments.mock_fail(db_session, invoice.id)
    with pytest.raises(PaymentProviderError):
        payments.mock_pay(db_session, invoice.id)
    assert billing.get_balance(db_session, account_id).balance_units == 0


def test_invoice_amount_immutable_after_pending(db_session: Session) -> None:
    _, payments = _svc(db_session)
    account_id = _account(db_session)
    invoice = payments.create_invoice(db_session, account_id, 500, idempotency_key="im")
    # Счёт уже в pending — сумму менять нельзя.
    with pytest.raises(PaymentProviderError):
        payments.set_invoice_amount(db_session, invoice.id, 999)
    payments.mock_pay(db_session, invoice.id)
    # После оплаты — тем более.
    with pytest.raises(PaymentProviderError):
        payments.set_invoice_amount(db_session, invoice.id, 1)
    assert payments.get_invoice(db_session, invoice.id).amount_units == 500
