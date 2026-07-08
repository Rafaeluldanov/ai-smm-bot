"""Тесты безопасного прогона проекта с биллингом (offline, SQLite)."""

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.api.deps import get_crm_bot_smm_application_service
from app.repositories import account_repository, post_repository, user_repository
from app.repositories import crm_bot_smm_repository as crm_repo
from app.schemas.saas_onboarding import SaasOnboardingPayload
from app.services.billing_service import BillingService, InsufficientBalanceError
from app.services.saas_bot_run_service import SaasBotRunError, SaasBotRunService
from app.services.saas_onboarding_service import SaasOnboardingService


def _account(db: Session, slug: str) -> int:
    user = user_repository.create_user(db, f"{slug}@example.com", "hash")
    return account_repository.create_account(db, slug, slug, user.id).id


def _payload(project_slug: str, topup: int) -> SaasOnboardingPayload:
    data: dict[str, Any] = {
        "company": {
            "company_name": "TEEON",
            "has_website": True,
            "website_url": "https://teeon.ru",
        },
        "project": {"project_slug": project_slug, "project_name": "TEEON"},
        "keywords": [{"query": "футболки с логотипом", "product": "футболка"}],
        "platforms": [
            {"platform_type": "telegram", "title": "TG", "external_id": "@teeon", "api_key": "S"}
        ],
        "promotion_categories": [
            {
                "title": "Футболки",
                "keyword_queries": ["футболки с логотипом"],
                "product_priorities": {"футболка": 5},
            }
        ],
        "publishing_plans": [
            {"category_title": "Футболки", "platforms": ["telegram"], "mode": "semi_auto"}
        ],
        "billing": {"starting_topup_amount": topup, "accept_terms": True},
    }
    return SaasOnboardingPayload.model_validate(data)


def _setup(db: Session, slug: str, topup: int) -> tuple[int, int, int]:
    account_id = _account(db, slug)
    result = SaasOnboardingService().apply(db, account_id, _payload(slug, topup))
    assert result.project_id is not None
    config = crm_repo.get_config_by_project_id(db, result.project_id)
    assert config is not None
    category = crm_repo.list_categories_by_config(db, config.id)[0]
    return account_id, result.project_id, category.id


def _run_service() -> SaasBotRunService:
    return SaasBotRunService(BillingService(), get_crm_bot_smm_application_service())


def test_dry_preview_estimates_without_debit(db_session: Session) -> None:
    account_id, project_id, category_id = _setup(db_session, "run-a", topup=100)
    result = _run_service().run_project_dry_preview(db_session, account_id, project_id, category_id)
    assert result.dry_run is True
    assert result.estimated_units > 0
    assert result.debited_units == 0
    assert result.balance_units == 100  # ничего не списано


def test_semi_auto_happy_path_runs_and_debits(db_session: Session) -> None:
    account_id, project_id, category_id = _setup(db_session, "run-ok", topup=1000)
    result = _run_service().run_project_semi_auto(db_session, account_id, project_id, category_id)

    assert result.dry_run is False
    assert result.published_publications == 0  # semi_auto: live выключен
    # Списание пропорционально созданным постам (0 постов → 0 units).
    assert result.debited_units == 10 * result.generated_posts
    assert result.balance_units == 1000 - result.debited_units
    assert (
        BillingService().get_balance(db_session, account_id).balance_units == result.balance_units
    )
    if result.generated_posts > 0:
        usage = BillingService().list_usage(db_session, account_id)
        assert any(u.event_type == "ai_generation" for u in usage)


def test_semi_auto_insufficient_balance_blocks_before_run(db_session: Session) -> None:
    account_id, project_id, category_id = _setup(db_session, "run-b", topup=0)
    with pytest.raises(InsufficientBalanceError):
        _run_service().run_project_semi_auto(db_session, account_id, project_id, category_id)
    # Прогон не запускался — баланс и посты не изменились.
    assert BillingService().get_balance(db_session, account_id).balance_units == 0
    assert post_repository.list_posts(db_session, project_id=project_id) == []


def test_ownership_mismatch_rejected(db_session: Session) -> None:
    account_id, project_id, category_id = _setup(db_session, "run-c", topup=100)
    other_account = _account(db_session, "other-acc")
    with pytest.raises(SaasBotRunError):
        _run_service().run_project_dry_preview(db_session, other_account, project_id, category_id)
