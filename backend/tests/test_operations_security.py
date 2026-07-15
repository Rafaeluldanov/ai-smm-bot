"""Статические + поведенческие проверки безопасности AI Operations Control Center (v0.7.3).

Инварианты:
- НЕ выполняет рекомендации автоматически, НЕ публикует, НЕ включает live, НЕ меняет CRM/
  бюджет/продажи, НЕ запускает рекламу; операции бесплатны (0 units); в представлениях нет секретов.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_operations_control_service import AIOperationsControlService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")

_MODULES = (
    "app.services.ai_operations_control_service",
    "app.repositories.operations_repository",
    "app.api.operations",
    "app.scripts.operations_analyze",
    "app.scripts.operations_report",
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


def test_config_flag_default_on() -> None:
    s = _SETTINGS
    assert s.operations_center_enabled is True
    assert s.operations_center_enabled_effective is True


def test_operations_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_OPERATIONS_ANALYSIS,
        billing_service.USAGE_OPERATIONS_REPORT,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_views_have_no_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="opssec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="opssec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="opssec"))
    project.account_id = account.id
    db_session.commit()
    svc = AIOperationsControlService(settings=_SETTINGS)
    svc.build_operations_snapshot(db_session, project.id)
    blob = (
        str(svc.get_operations(db_session, project.id))
        + str(svc.list_active_risks(db_session, project.id))
        + str(svc.list_recommendations(db_session, project.id))
    )
    for token in ("api_key", "token", "secret", "password"):
        assert token not in blob.lower()
