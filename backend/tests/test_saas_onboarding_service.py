"""Тесты сервиса SaaS-онбординга (offline, SQLite; переиспользует CRM)."""

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.models.account import Account
from app.repositories import (
    account_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    crm_bot_smm_repository as crm_repo,
)
from app.schemas.saas_onboarding import SaasOnboardingPayload
from app.services.saas_onboarding_service import SaasOnboardingError, SaasOnboardingService


def _account(db: Session, slug: str = "acme") -> Account:
    user = user_repository.create_user(db, f"{slug}@example.com", "hash")
    return account_repository.create_account(db, "Acme", slug, user.id)


def _payload(
    project_slug: str = "teeon-x", live: bool = False, accept: bool = True
) -> SaasOnboardingPayload:
    data: dict[str, Any] = {
        "company": {
            "company_name": "TEEON",
            "has_website": True,
            "website_url": "https://teeon.ru",
            "business_description": "Мерч под ключ",
        },
        "project": {"project_slug": project_slug, "project_name": "TEEON"},
        "keywords": [{"query": "футболки с логотипом", "product": "футболка"}],
        "media_sources": [
            {"source_type": "yandex_disk", "title": "Диск", "url": "https://disk.yandex.ru/x"}
        ],
        "platforms": [
            {
                "platform_type": "telegram",
                "title": "TG",
                "external_id": "@teeon",
                "api_key": "SECRET_TOKEN",
                "live_enabled": live,
            }
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
        "billing": {"starting_topup_amount": 50, "accept_terms": accept},
    }
    return SaasOnboardingPayload.model_validate(data)


def test_form_schema_has_expected_sections() -> None:
    schema = SaasOnboardingService().build_form_schema()
    keys = {s.key for s in schema.sections}
    assert {"company", "project", "keywords", "media_sources", "platforms", "billing"} <= keys


def test_preview_validates_without_writing(db_session: Session) -> None:
    account = _account(db_session)
    result = SaasOnboardingService().preview(db_session, account.id, _payload())
    assert result.dry_run is True
    assert result.project_id is None
    assert project_repository.get_project_by_slug(db_session, "teeon-x") is None


def test_apply_creates_project_config_under_account(db_session: Session) -> None:
    account = _account(db_session)
    result = SaasOnboardingService().apply(db_session, account.id, _payload())
    project = project_repository.get_project_by_slug(db_session, "teeon-x")
    assert project is not None
    assert project.account_id == account.id
    assert result.project_id == project.id
    config = crm_repo.get_config_by_project_id(db_session, project.id)
    assert config is not None
    assert len(crm_repo.list_resources_by_config(db_session, config.id)) == 1
    assert len(crm_repo.list_content_sources_by_config(db_session, config.id)) == 1
    assert len(crm_repo.list_categories_by_config(db_session, config.id)) == 1
    # Стартовое пополнение начислено.
    assert result.billing_balance_units == 50


def test_api_key_masked_not_returned(db_session: Session) -> None:
    account = _account(db_session)
    result = SaasOnboardingService().apply(db_session, account.id, _payload())
    assert "SECRET_TOKEN" not in result.model_dump_json()
    assert all(r.api_key_present for r in result.crm.resources)


def test_live_enabled_rejected_without_admin(db_session: Session) -> None:
    account = _account(db_session)
    service = SaasOnboardingService()
    with pytest.raises(SaasOnboardingError):
        service.preview(db_session, account.id, _payload(live=True))
    # С allow_live запрос принимается, но live остаётся выключенным (warning).
    result = service.preview(db_session, account.id, _payload(live=True), allow_live=True)
    assert any("ВЫКЛЮЧЕН" in w for w in result.warnings)


def test_live_never_persisted_even_with_allow_live(db_session: Session) -> None:
    account = _account(db_session)
    service = SaasOnboardingService()
    result = service.apply(db_session, account.id, _payload(live=True), allow_live=True)
    project = project_repository.get_project_by_slug(db_session, "teeon-x")
    assert project is not None
    config = crm_repo.get_config_by_project_id(db_session, project.id)
    assert config is not None
    resources = crm_repo.list_resources_by_config(db_session, config.id)
    assert all(not r.live_enabled for r in resources)
    assert result.project_id == project.id


def test_multiple_projects_per_account(db_session: Session) -> None:
    account = _account(db_session)
    service = SaasOnboardingService()
    service.apply(db_session, account.id, _payload(project_slug="proj-a"))
    service.apply(db_session, account.id, _payload(project_slug="proj-b"))
    projects = service.list_account_projects(db_session, account.id)
    assert {p.slug for p in projects} == {"proj-a", "proj-b"}


def test_apply_requires_accept_terms(db_session: Session) -> None:
    account = _account(db_session)
    with pytest.raises(SaasOnboardingError):
        SaasOnboardingService().apply(db_session, account.id, _payload(accept=False))


def test_apply_unknown_account_rejected(db_session: Session) -> None:
    with pytest.raises(SaasOnboardingError):
        SaasOnboardingService().apply(db_session, 99999, _payload())


def test_slug_owned_by_another_account_rejected_no_takeover(db_session: Session) -> None:
    account_a = _account(db_session, "acc-a")
    account_b = _account(db_session, "acc-b")
    service = SaasOnboardingService()
    service.apply(db_session, account_a.id, _payload(project_slug="shared"))

    # Аккаунт B не может «захватить» проект A с тем же slug.
    with pytest.raises(SaasOnboardingError):
        service.apply(db_session, account_b.id, _payload(project_slug="shared"))

    project = project_repository.get_project_by_slug(db_session, "shared")
    assert project is not None
    assert project.account_id == account_a.id  # остался у A
    assert service.list_account_projects(db_session, account_b.id) == []


def test_reapply_same_account_is_idempotent(db_session: Session) -> None:
    account = _account(db_session)
    service = SaasOnboardingService()
    first = service.apply(db_session, account.id, _payload(project_slug="reapply"))
    second = service.apply(db_session, account.id, _payload(project_slug="reapply"))
    assert first.project_id == second.project_id
    assert len(service.list_account_projects(db_session, account.id)) == 1


def test_dashboard_summary(db_session: Session) -> None:
    account = _account(db_session)
    service = SaasOnboardingService()
    result = service.apply(db_session, account.id, _payload())
    assert result.project_id is not None
    dashboard = service.build_dashboard(db_session, result.project_id)
    assert dashboard.account_id == account.id
    assert dashboard.platforms_count == 1
    assert dashboard.media_sources_count == 1
    assert dashboard.categories_count == 1
    assert dashboard.billing_balance_units == 50
    assert dashboard.next_recommended_actions
