"""Тесты биллинга аналитики (offline): цена по глубине, dry-run бесплатно,
запуск списывает units, недостаток блокирует, идемпотентность.
"""

import pytest
from sqlalchemy.orm import Session

from app.repositories import account_repository, post_repository, user_repository
from app.repositories.project_repository import create_project
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService, InsufficientBalanceError
from app.services.post_analytics_service import PostAnalyticsService


def _setup(db: Session, balance: int = 0) -> tuple[int, int]:
    user = user_repository.create_user(db, email="an@e.com", password_hash="x")
    account = account_repository.create_account(db, name="A", slug="a", owner_user_id=user.id)
    project = create_project(db, ProjectCreate(name="P", slug="proj"))
    project.account_id = account.id
    db.commit()
    post_repository.create_post(
        db,
        PostCreate(project_id=project.id, title="t", telegram_text="hi", status="published"),
    )
    billing = BillingService()
    billing.get_or_create_billing_account(db, account.id)
    if balance:
        billing.manual_topup(db, account.id, balance, idempotency_key="seed")
    return account.id, project.id


def test_cost_by_depth(db_session: Session) -> None:
    svc = PostAnalyticsService()
    from app.services.unit_economics_service import UnitEconomicsService

    econ = UnitEconomicsService()
    assert econ.estimate_analytics_units("light", 1) == 10
    assert econ.estimate_analytics_units("standard", 1) == 20
    assert econ.estimate_analytics_units("deep", 1) == 40
    account_id, project_id = _setup(db_session, balance=100)
    preview = svc.preview_analytics_cost(db_session, account_id, "deep", 1)
    assert preview["estimated_units"] == 40
    assert preview["affordable"] is True


def test_dry_run_is_free(db_session: Session) -> None:
    svc = PostAnalyticsService()
    billing = BillingService()
    account_id, project_id = _setup(db_session, balance=100)
    before = billing.get_balance(db_session, account_id).balance_units
    result = svc.run_analytics_dry(db_session, account_id, project_id, "deep")
    assert result["charged_units"] == 0
    assert billing.get_balance(db_session, account_id).balance_units == before


def test_run_debits_units_once(db_session: Session) -> None:
    svc = PostAnalyticsService()
    billing = BillingService()
    account_id, project_id = _setup(db_session, balance=100)
    result = svc.run_analytics(db_session, account_id, project_id, "deep", idempotency_key="run-1")
    assert result["charged_units"] == 40
    assert billing.get_balance(db_session, account_id).balance_units == 60
    # Идемпотентность: повтор с тем же ключом не списывает второй раз.
    svc.run_analytics(db_session, account_id, project_id, "deep", idempotency_key="run-1")
    assert billing.get_balance(db_session, account_id).balance_units == 60


def test_insufficient_balance_blocks_run(db_session: Session) -> None:
    svc = PostAnalyticsService()
    billing = BillingService()
    account_id, project_id = _setup(db_session, balance=5)  # < 40
    with pytest.raises(InsufficientBalanceError):
        svc.run_analytics(db_session, account_id, project_id, "deep", idempotency_key="run-x")
    # Баланс не изменился, в минус не ушёл.
    assert billing.get_balance(db_session, account_id).balance_units == 5
