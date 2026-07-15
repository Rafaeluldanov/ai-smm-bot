"""Статические + поведенческие проверки безопасности AI Decision Engine (v0.7.4).

Инварианты:
- НЕ применяет решения автоматически, НЕ публикует, НЕ включает live, НЕ меняет CRM/бюджет/
  продажи, НЕ запускает рекламу; apply лишь создаёт draft workflow; 0 units; нет секретов.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_decision_engine_service import APPLY_CONFIRMATION, AIDecisionEngineService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")

_MODULES = (
    "app.services.ai_decision_engine_service",
    "app.repositories.decision_repository",
    "app.api.decisions",
    "app.scripts.decision_create",
    "app.scripts.decision_analyze",
    "app.scripts.decision_report",
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


def test_config_flags_default() -> None:
    s = _SETTINGS
    assert s.decision_engine_enabled is True
    assert s.decision_engine_enabled_effective is True
    assert s.decision_engine_auto_apply_enabled is False
    assert s.decision_engine_auto_apply_enabled_effective is False


def test_decision_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_DECISION_ANALYSIS,
        billing_service.USAGE_DECISION_REPORT,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_apply_only_creates_draft_no_live(db_session: Session) -> None:
    """apply создаёт лишь draft workflow (не запускает), live_enabled=False."""
    from app.models.business_workflow import BusinessWorkflow
    from app.models.post_publication import PostPublication

    owner = user_repository.create_user(db_session, email="decsec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="decsec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="decsec"))
    project.account_id = account.id
    db_session.commit()
    svc = AIDecisionEngineService(settings=_SETTINGS)
    did = svc.create_decision(db_session, project.id, decision_type="sales", title="P")["id"]
    svc.analyze_decision(db_session, did)
    svc.accept_decision(db_session, did)
    res = svc.apply_decision(db_session, did, confirmation=APPLY_CONFIRMATION)
    assert res["live_enabled"] is False
    wfs = db_session.query(BusinessWorkflow).filter_by(project_id=project.id).all()
    assert all(w.status == "draft" for w in wfs)
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_views_have_no_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="decsec2@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="decsec2", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="decsec2"))
    project.account_id = account.id
    db_session.commit()
    svc = AIDecisionEngineService(settings=_SETTINGS)
    did = svc.create_decision(db_session, project.id, decision_type="growth", title="P")["id"]
    svc.analyze_decision(db_session, did)
    blob = str(svc.get_decision(db_session, did)) + str(svc.list_decisions(db_session, project.id))
    for token in ("api_key", "token", "secret", "password"):
        assert token not in blob.lower()
