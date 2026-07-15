"""Статические + поведенческие проверки безопасности Autonomous Business OS (v0.7.0).

Инварианты:
- НЕ публикует, НЕ включает live, НЕ меняет CRM/бюджет, НЕ запускает рекламу;
- auto_apply выключен по умолчанию; операции бесплатны (0 units); в представлениях нет секретов.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_executive_service import AIExecutiveService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")

_MODULES = (
    "app.services.ai_executive_service",
    "app.repositories.business_os_repository",
    "app.api.business_os",
    "app.scripts.business_os_analyze",
    "app.scripts.business_os_plan",
    "app.scripts.business_os_apply",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_no_live_no_crm_no_ads() -> None:
    for module in _MODULES:
        src = _source(module)
        assert "publish_once_if_allowed" not in src, module
        assert "publish_post(" not in src, module
        assert "apply_calendar_to_project" not in src, module
        assert "create_lead(" not in src, module  # не создаёт CRM-лиды
        assert "record_lead_event" not in src, module  # не пишет продажи/выручку
        low = src.lower()
        assert "live_publishing_enabled =" not in low, module
        for ads in ("adwords", "facebook_ads", "vk_ads", "yandex_direct"):
            assert ads not in low, f"{module}: {ads}"


def test_config_auto_apply_off_by_default() -> None:
    s = _SETTINGS
    assert s.business_os_auto_apply_enabled is False
    assert s.business_os_auto_apply_enabled_effective is False
    assert s.business_os_enabled is True


def test_business_os_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_BUSINESS_OS_ANALYSIS,
        billing_service.USAGE_BUSINESS_OS_PLAN,
        billing_service.USAGE_BUSINESS_OS_APPLY,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_views_have_no_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="exsec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="exsec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="exsec"))
    project.account_id = account.id
    db_session.commit()
    svc = AIExecutiveService(settings=_SETTINGS)
    svc.create_objective(db_session, project.id, type="revenue_growth", title="Цель")
    svc.create_executive_plan(db_session, project.id)
    blob = (
        str(svc.get_plan(db_session, project.id))
        + str(svc.list_actions(db_session, project.id))
        + str(svc.list_objectives(db_session, project.id))
    )
    for token in ("api_key", "token", "secret", "password"):
        assert token not in blob.lower()
