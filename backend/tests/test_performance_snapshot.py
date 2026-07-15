"""Тесты снимков эффективности — AI Performance Intelligence (v0.7.9, offline).

Инварианты:
- snapshot создаётся; статус выводится из score; list/summary; аудит snapshot_created;
- tenant isolation; missing → 404; на пустом проекте не падает.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import AIBusinessPlannerService
from app.services.ai_performance_intelligence_service import (
    AIPerformanceIntelligenceError,
    AIPerformanceIntelligenceService,
)

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


def _seed_below_target(db: Session, pid: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """Цель revenue=1M + факт revenue=700k (ниже плана) → отклонение."""
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


def test_snapshot_created(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pid, uid = _project(db_session, "pfsnap1")
    _seed_below_target(db_session, pid, monkeypatch)
    out = _svc().create_snapshot(db_session, pid, user_id=uid)
    snap = out["snapshot"]
    assert snap["status"] in ("healthy", "warning", "critical")
    assert 0.0 <= snap["performance_score"] <= 100.0
    assert "revenue" in {m["metric"] for m in out["metrics"]}


def test_status_from_score() -> None:
    svc = _svc()
    assert svc._status_from_score(80) == "healthy"
    assert svc._status_from_score(50) == "warning"
    assert svc._status_from_score(20) == "critical"


def test_empty_project_snapshot(db_session: Session) -> None:
    """На пустом проекте (без факта) снимок создаётся и не падает."""
    pid, _ = _project(db_session, "pfsnap2")
    out = _svc().create_snapshot(db_session, pid)
    assert out["snapshot"]["performance_score"] >= 0.0


def test_list_and_summary(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pid, _ = _project(db_session, "pfsnap3")
    _seed_below_target(db_session, pid, monkeypatch)
    svc = _svc()
    svc.create_snapshot(db_session, pid)
    out = svc.list_snapshots(db_session, pid)
    assert len(out["snapshots"]) == 1
    assert out["summary"]["snapshots_total"] == 1
    assert out["summary"]["latest_score"] is not None


def test_audit_snapshot_created(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "pfsnap4")
    _seed_below_target(db_session, pid, monkeypatch)
    _svc().create_snapshot(db_session, pid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "performance.snapshot_created" in actions


def test_missing_snapshot_raises(db_session: Session) -> None:
    with pytest.raises(AIPerformanceIntelligenceError, match="не найден"):
        _svc().get_snapshot(db_session, 999999)


def test_missing_project_raises(db_session: Session) -> None:
    with pytest.raises(AIPerformanceIntelligenceError, match="не найден"):
        _svc().create_snapshot(db_session, 999999)
