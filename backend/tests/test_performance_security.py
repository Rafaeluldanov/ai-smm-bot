"""Тесты безопасности AI Performance Intelligence (v0.7.9, offline).

Жёсткие инварианты (Часть 18): запрещено менять планы автоматически, менять KPI, выполнять
рекомендации, менять бизнес. Аналитический слой:
- analyze НЕ меняет планы/цели/исполнение, НЕ публикует, НЕ включает live, НЕ создаёт процессов;
- бесплатно (0 units); секретов нет; tenant isolation; переживает падение всех смежных слоёв.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.business_workflow import BusinessWorkflow
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import AIBusinessPlannerService
from app.services.ai_performance_intelligence_service import AIPerformanceIntelligenceService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_KEYS = ("token", "secret", "password", "api_key", "access_token", "refresh_token")


def _svc() -> AIPerformanceIntelligenceService:
    return AIPerformanceIntelligenceService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _below(db: Session, pid: int, monkeypatch: pytest.MonkeyPatch) -> None:
    AIBusinessPlannerService(settings=_SETTINGS).create_business_goal(
        db, pid, goal_type="revenue", title="rev", target_value=1000000, current_value=100000
    )
    monkeypatch.setattr(
        "app.repositories.business_growth_repository.get_profile",
        lambda *_a, **_k: SimpleNamespace(
            current_state={"total_revenue": 700000.0, "conversion_rate": 0.1, "leads": 50},
            growth_score=40.0,
        ),
    )


def test_billing_is_free() -> None:
    from app.services.billing_service import (
        ACTION_COSTS,
        USAGE_PERFORMANCE_ANALYSIS,
        USAGE_PERFORMANCE_REPORT,
    )

    assert ACTION_COSTS[USAGE_PERFORMANCE_ANALYSIS] == 0
    assert ACTION_COSTS[USAGE_PERFORMANCE_REPORT] == 0


def test_analyze_does_not_mutate_plans_or_publish(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, _ = _project(db_session, "pfsec1")
    _below(db_session, pid, monkeypatch)
    # цель до анализа
    from app.repositories import business_planner_repository as planner_repo

    goal_before = planner_repo.list_goals(db_session, pid)[0]
    target_before = goal_before.target_value
    _svc().create_snapshot(db_session, pid)
    # анализ НЕ меняет цель/KPI, НЕ создаёт процессов, НЕ публикует
    goal_after = planner_repo.list_goals(db_session, pid)[0]
    assert goal_after.target_value == target_before
    assert db_session.query(BusinessWorkflow).filter_by(project_id=pid).count() == 0
    assert db_session.query(PostPublication).count() == 0


def test_analyze_is_read_only_no_growth_mutation(db_session: Session) -> None:
    """analyze НЕ создаёт/не меняет BusinessGrowthProfile и НЕ пишет growth.analyzed (read-only)."""
    from app.models.audit_log import AuditLogEntry
    from app.models.business_growth_profile import BusinessGrowthProfile

    pid, _ = _project(db_session, "pfsec1b")
    assert db_session.query(BusinessGrowthProfile).filter_by(project_id=pid).count() == 0
    _svc().create_snapshot(db_session, pid)
    # анализ НЕ создал профиль роста и НЕ записал growth.analyzed
    assert db_session.query(BusinessGrowthProfile).filter_by(project_id=pid).count() == 0
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "growth.analyzed" not in actions


def test_public_views_have_no_secrets(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pid, _ = _project(db_session, "pfsec2")
    _below(db_session, pid, monkeypatch)
    svc = _svc()
    out = svc.create_snapshot(db_session, pid)
    blob = (str(out) + str(svc.explain_performance(db_session, out["snapshot"]["id"]))).lower()
    for key in _SECRET_KEYS:
        assert key not in blob


def test_score_bounded(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pid, _ = _project(db_session, "pfsec3")
    _below(db_session, pid, monkeypatch)
    snap = _svc().create_snapshot(db_session, pid)["snapshot"]
    assert 0.0 <= snap["performance_score"] <= 100.0
    assert snap["status"] in ("healthy", "warning", "critical")


def test_cross_tenant_snapshot_isolated(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid1, _ = _project(db_session, "pfsec4a")
    _pid2, _ = _project(db_session, "pfsec4b")
    _below(db_session, pid1, monkeypatch)
    snap = _svc().create_snapshot(db_session, pid1)["snapshot"]
    assert _svc().get_snapshot(db_session, snap["id"])["snapshot"]["project_id"] == pid1


def test_analyze_survives_all_layers_down(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Падение ВСЕХ смежных слоёв НЕ роняет анализ — снимок всё равно создаётся."""
    pid, _ = _project(db_session, "pfsec5")

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("layer down")

    monkeypatch.setattr("app.repositories.business_growth_repository.get_profile", _boom)
    monkeypatch.setattr("app.repositories.business_planner_repository.list_goals", _boom)
    monkeypatch.setattr("app.repositories.business_forecast_repository.get_latest_forecast", _boom)
    monkeypatch.setattr("app.repositories.execution_repository.list_execution_plans", _boom)
    monkeypatch.setattr("app.repositories.operations_repository.list_active_risks", _boom)
    monkeypatch.setattr("app.repositories.operations_repository.get_latest_snapshot", _boom)
    out = _svc().create_snapshot(db_session, pid)  # не падает
    assert 0.0 <= out["snapshot"]["performance_score"] <= 100.0
