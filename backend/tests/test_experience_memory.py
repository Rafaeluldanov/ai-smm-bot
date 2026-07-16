"""Тесты памяти опыта — AI Continuous Improvement (v0.8.0, offline).

Инварианты:
- capture_experience собирает опыт из Performance/Execution/Decision (read-only); outcome выводится;
- history; аудит experience_created; tenant; на пустом проекте не падает.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import performance_repository as perf_repo
from app.schemas.project import ProjectCreate
from app.services.ai_continuous_improvement_service import AIContinuousImprovementService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIContinuousImprovementService:
    return AIContinuousImprovementService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _seed_perf(db: Session, pid: int, *, status: str = "critical", score: float = 25.0) -> int:
    snap = perf_repo.create_snapshot(
        db,
        project_id=pid,
        account_id=None,
        status=status,
        performance_score=score,
        target_state={"revenue": 1000},
        actual_state={"revenue": 300},
    )
    perf_repo.create_deviation(
        db, snapshot_id=snap.id, metric="revenue", title="revenue -70%", impact="critical"
    )
    return snap.id


def test_capture_performance_experience(db_session: Session) -> None:
    pid, uid = _project(db_session, "exp1")
    _seed_perf(db_session, pid, status="critical")
    created = _svc().capture_experience(db_session, pid, user_id=uid)
    perf = [e for e in created if e["experience_type"] == "performance"]
    assert perf and perf[0]["outcome"] == "failure"  # critical → failure


def test_outcome_maps_from_status(db_session: Session) -> None:
    pid, _ = _project(db_session, "exp2")
    _seed_perf(db_session, pid, status="healthy", score=85.0)
    created = _svc().capture_experience(db_session, pid)
    perf = [e for e in created if e["experience_type"] == "performance"][0]
    assert perf["outcome"] == "success"  # healthy → success


def test_empty_project_capture(db_session: Session) -> None:
    """На пустом проекте (нет источников) capture ничего не создаёт и не падает."""
    pid, _ = _project(db_session, "exp3")
    created = _svc().capture_experience(db_session, pid)
    assert created == []


def test_history_and_summary(db_session: Session) -> None:
    pid, _ = _project(db_session, "exp4")
    _seed_perf(db_session, pid)
    svc = _svc()
    svc.capture_experience(db_session, pid)
    hist = svc.get_history(db_session, pid)
    assert hist["summary"]["experiences_total"] >= 1


def test_audit_experience_created(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "exp5")
    _seed_perf(db_session, pid)
    _svc().capture_experience(db_session, pid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "learning.experience_created" in actions


def test_analyze_outcome_pure() -> None:
    svc = _svc()
    assert svc.analyze_outcome({"revenue": 100}, {"revenue": 95}) == "success"
    assert svc.analyze_outcome({"revenue": 100}, {"revenue": 70}) == "neutral"
    assert svc.analyze_outcome({"revenue": 100}, {"revenue": 40}) == "failure"
    assert svc.analyze_outcome({}, {}) == "neutral"
