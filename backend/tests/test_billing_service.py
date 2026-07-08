"""Тесты сервиса биллинга (offline, SQLite; без реальных платежей)."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import account_repository, billing_repository, user_repository
from app.services.billing_service import (
    BillingError,
    BillingService,
    InsufficientBalanceError,
)


def _account_id(db: Session, email: str = "u@example.com", slug: str = "acme") -> int:
    user = user_repository.create_user(db, email, "hash")
    return account_repository.create_account(db, "Acme", slug, user.id).id


def test_manual_topup(db_session: Session) -> None:
    account_id = _account_id(db_session)
    service = BillingService()
    entry = service.manual_topup(db_session, account_id, 500)
    assert entry.entry_type == "topup"
    assert entry.amount_units == 500
    assert entry.balance_after_units == 500
    assert service.get_balance(db_session, account_id).balance_units == 500


def test_debit_creates_usage_event(db_session: Session) -> None:
    account_id = _account_id(db_session)
    service = BillingService()
    service.manual_topup(db_session, account_id, 100)
    entry = service.reserve_or_debit(db_session, account_id, "ai_generation", 10)
    assert entry.entry_type == "debit"
    assert entry.amount_units == -10
    assert service.get_balance(db_session, account_id).balance_units == 90
    usage = service.list_usage(db_session, account_id)
    assert len(usage) == 1
    assert usage[0].event_type == "ai_generation"
    assert usage[0].units == 10


def test_insufficient_balance_blocks_action(db_session: Session) -> None:
    account_id = _account_id(db_session)
    service = BillingService()
    service.manual_topup(db_session, account_id, 5)
    with pytest.raises(InsufficientBalanceError):
        service.reserve_or_debit(db_session, account_id, "ai_generation", 10)
    # Баланс не изменился, usage не создан.
    assert service.get_balance(db_session, account_id).balance_units == 5
    assert service.list_usage(db_session, account_id) == []


def test_idempotency_key_prevents_double_topup(db_session: Session) -> None:
    account_id = _account_id(db_session)
    service = BillingService()
    service.manual_topup(db_session, account_id, 100, idempotency_key="topup-1")
    service.manual_topup(db_session, account_id, 100, idempotency_key="topup-1")
    assert service.get_balance(db_session, account_id).balance_units == 100
    assert len(service.list_ledger(db_session, account_id)) == 1


def test_idempotency_key_prevents_double_debit(db_session: Session) -> None:
    account_id = _account_id(db_session)
    service = BillingService()
    service.manual_topup(db_session, account_id, 100)
    service.reserve_or_debit(db_session, account_id, "ai_generation", 10, idempotency_key="debit-1")
    service.reserve_or_debit(db_session, account_id, "ai_generation", 10, idempotency_key="debit-1")
    assert service.get_balance(db_session, account_id).balance_units == 90
    # Ровно одно usage-событие и одна debit-запись в журнале (без дублей).
    assert len(service.list_usage(db_session, account_id)) == 1
    debit_entries = [
        e for e in service.list_ledger(db_session, account_id) if e.entry_type == "debit"
    ]
    assert len(debit_entries) == 1


def test_estimate_action_cost(db_session: Session) -> None:
    service = BillingService()
    assert service.estimate_action_cost("ai_generation") == 10
    assert service.estimate_action_cost("ai_generation", {"count": 3}) == 30
    assert service.estimate_action_cost("publication_preview") == 1
    assert service.estimate_action_cost("unknown_action") == 1


def test_tariff_included_units_seeded_on_create(db_session: Session) -> None:
    account_id = _account_id(db_session)
    billing_repository.create_tariff(db_session, "starter", "Starter", included_units=50)
    service = BillingService()
    billing = service.get_or_create_billing_account(db_session, account_id, "starter")
    assert billing.balance_units == 50
    assert billing.tariff_plan_slug == "starter"


def test_refund_returns_units(db_session: Session) -> None:
    account_id = _account_id(db_session)
    service = BillingService()
    service.manual_topup(db_session, account_id, 100)
    service.reserve_or_debit(db_session, account_id, "ai_generation", 10)
    service.refund(db_session, account_id, 10)
    assert service.get_balance(db_session, account_id).balance_units == 100


def test_topup_rejects_non_positive(db_session: Session) -> None:
    account_id = _account_id(db_session)
    service = BillingService()
    with pytest.raises(BillingError):
        service.manual_topup(db_session, account_id, 0)
