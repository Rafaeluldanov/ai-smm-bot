"""Статические + поведенческие проверки безопасности AI Chief of Staff (v0.7.1).

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
from app.services.ai_chief_of_staff_service import AIChiefOfStaffService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")

_MODULES = (
    "app.services.ai_chief_of_staff_service",
    "app.repositories.chief_of_staff_repository",
    "app.api.chief_of_staff",
    "app.scripts.chief_briefing",
    "app.scripts.chief_tasks",
    "app.scripts.chief_memory",
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
    assert s.chief_of_staff_enabled is True
    assert s.chief_of_staff_enabled_effective is True


def test_chief_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_CHIEF_BRIEFING,
        billing_service.USAGE_CHIEF_TASKS,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_views_have_no_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="chsec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="chsec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="chsec"))
    project.account_id = account.id
    db_session.commit()
    svc = AIChiefOfStaffService(settings=_SETTINGS)
    svc.generate_daily_briefing(db_session, project.id)
    svc.save_decision_memory(
        db_session, project.id, decision_type="preference", key="k", value={"v": 1}
    )
    blob = (
        str(svc.get_latest_briefing(db_session, project.id))
        + str(svc.list_tasks(db_session, project.id))
        + str(svc.get_decisions(db_session, project.id))
    )
    for token in ("api_key", "token", "secret", "password"):
        assert token not in blob.lower()
