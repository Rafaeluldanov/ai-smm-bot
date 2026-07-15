"""Статические + поведенческие проверки безопасности AI Workflow Manager (v0.7.2).

Инварианты:
- НЕ выполняет задачи автоматически, НЕ публикует, НЕ включает live, НЕ меняет CRM/бюджет/
  продажи, НЕ запускает рекламу; операции бесплатны (0 units); в представлениях нет секретов.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_workflow_manager_service import AIWorkflowManagerService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")

_MODULES = (
    "app.services.ai_workflow_manager_service",
    "app.repositories.workflow_repository",
    "app.api.workflows",
    "app.scripts.workflow_create",
    "app.scripts.workflow_status",
    "app.scripts.workflow_analyze",
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
    assert s.workflow_manager_enabled is True
    assert s.workflow_manager_enabled_effective is True


def test_workflow_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_WORKFLOW_CREATE,
        billing_service.USAGE_WORKFLOW_ANALYSIS,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_views_have_no_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="wfsec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="wfsec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="wfsec"))
    project.account_id = account.id
    db_session.commit()
    svc = AIWorkflowManagerService(settings=_SETTINGS)
    wid = svc.create_workflow_from_goal(
        db_session, project.id, name="P", workflow_type="growth", status="active"
    )["id"]
    svc.generate_workflow_steps(db_session, wid)
    svc.create_blocker(db_session, wid, blocker_type="resource", title="b")
    blob = str(svc.get_workflow(db_session, wid)) + str(svc.list_workflows(db_session, project.id))
    for token in ("api_key", "token", "secret", "password"):
        assert token not in blob.lower()
