"""Тесты метрик/сравнения план vs факт — AI Performance Intelligence (v0.7.9, offline).

Инварианты:
- compare_metrics: difference=actual−target, %, статус по порогам; метрики без плана пропускаются;
- статусы/impact по порогам; метрики персистятся в снимок.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import performance_repository as repo
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import AIBusinessPlannerService
from app.services.ai_performance_intelligence_service import AIPerformanceIntelligenceService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIPerformanceIntelligenceService:
    return AIPerformanceIntelligenceService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


# --- Прямые проверки сравнения/порогов (чистые функции) --- #


def test_compare_difference_and_percent() -> None:
    svc = _svc()
    comparison = svc.compare_metrics({"revenue": 70.0}, {"revenue": 100.0, "execution": 0.0})
    rev = [c for c in comparison if c["metric"] == "revenue"][0]
    assert rev["difference"] == -30.0
    assert rev["difference_percent"] == -30.0
    assert rev["status"] == "critical"


def test_metrics_without_target_skipped() -> None:
    svc = _svc()
    comparison = svc.compare_metrics({"revenue": 50.0, "leads": 10.0}, {"revenue": 0.0})
    assert comparison == []  # план 0 → метрика не оценивается


def test_metric_status_thresholds() -> None:
    svc = _svc()
    assert svc._metric_status(0.0) == "healthy"
    assert svc._metric_status(-4.0) == "healthy"
    assert svc._metric_status(-10.0) == "warning"
    assert svc._metric_status(-40.0) == "critical"


def test_positive_deviation_healthy() -> None:
    """Факт выше плана → healthy (положительное отклонение не наказывается)."""
    svc = _svc()
    comparison = svc.compare_metrics({"revenue": 120.0}, {"revenue": 100.0})
    assert comparison[0]["status"] == "healthy" and comparison[0]["difference_percent"] == 20.0


def test_impact_from_deviation() -> None:
    svc = _svc()
    assert svc._impact_from_deviation(-10.0) == "low"
    assert svc._impact_from_deviation(-20.0) == "medium"
    assert svc._impact_from_deviation(-40.0) == "high"
    assert svc._impact_from_deviation(-60.0) == "critical"


# --- Персистентность метрик --- #


def test_metric_rows_persisted(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pid, _ = _project(db_session, "pfmet1")
    AIBusinessPlannerService(settings=_SETTINGS).create_business_goal(
        db_session, pid, goal_type="revenue", title="rev", target_value=1000, current_value=100
    )
    monkeypatch.setattr(
        "app.repositories.business_growth_repository.get_profile",
        lambda *_a, **_k: SimpleNamespace(
            current_state={"total_revenue": 600.0, "conversion_rate": 0.2, "leads": 30},
            growth_score=50.0,
        ),
    )
    out = _svc().create_snapshot(db_session, pid)
    rows = repo.list_metrics(db_session, out["snapshot"]["id"])
    metrics = {r.metric for r in rows}
    assert "revenue" in metrics
    for r in rows:
        assert r.status in ("healthy", "warning", "critical")
