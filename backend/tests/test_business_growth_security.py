"""Статические + поведенческие проверки безопасности AI Business Growth Agent (v0.6.9).

Инварианты:
- НЕ меняет CRM/продажи/бюджет, НЕ запускает рекламу, НЕ включает live, НЕ публикует;
- auto_apply выключен по умолчанию; операции бесплатны (0 units); секретов нет.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.business_growth_agent_service import BusinessGrowthAgentService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")

_MODULES = (
    "app.services.business_growth_agent_service",
    "app.repositories.business_growth_repository",
    "app.api.business_growth",
    "app.scripts.growth_analyze",
    "app.scripts.growth_report",
    "app.scripts.growth_apply",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_no_live_no_crm_no_ads() -> None:
    for module in _MODULES:
        src = _source(module)
        assert "publish_once_if_allowed" not in src, module
        assert "publish_post(" not in src, module
        # НЕ активирует календарь/расписание и не меняет CRM.
        assert "apply_calendar_to_project" not in src, module
        assert "create_lead(" not in src, module  # не создаёт лиды в CRM
        low = src.lower()
        assert "live_publishing_enabled =" not in low, module
        for ads in ("adwords", "facebook_ads", "vk_ads", "yandex_direct"):
            assert ads not in low, f"{module}: {ads}"


def test_config_auto_apply_off_by_default() -> None:
    fields = set(Settings.model_fields)
    assert not any("business_growth" in f and "live" in f for f in fields)
    s = _SETTINGS
    assert s.business_growth_auto_apply_enabled is False
    assert s.business_growth_auto_apply_enabled_effective is False
    assert s.business_growth_enabled is True


def test_growth_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_BUSINESS_GROWTH_ANALYSIS,
        billing_service.USAGE_BUSINESS_GROWTH_REPORT,
        billing_service.USAGE_BUSINESS_GROWTH_APPLY,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_views_have_no_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="bgsec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="bgsec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="bgsec"))
    project.account_id = account.id
    db_session.commit()
    svc = BusinessGrowthAgentService(settings=_SETTINGS)
    svc.analyze_business(db_session, project.id)
    blob = str(svc.get_growth(db_session, project.id)) + str(
        svc.list_recommendations(db_session, project.id)
    )
    for token in ("api_key", "token", "secret", "password"):
        assert token not in blob.lower()
