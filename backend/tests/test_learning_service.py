"""Тесты AIContinuousImprovementService — цикл обучения (v0.8.0, offline).

Инварианты:
- run_learning_cycle строит опыт → события → паттерны → улучшения; events из опыта;
- explain_learning; аудит lifecycle; НЕ меняет бизнес.
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


def _seed_failing(db: Session, pid: int) -> None:
    snap = perf_repo.create_snapshot(
        db,
        project_id=pid,
        account_id=None,
        status="critical",
        performance_score=25.0,
        target_state={"revenue": 1000},
        actual_state={"revenue": 300},
    )
    perf_repo.create_deviation(
        db, snapshot_id=snap.id, metric="revenue", title="revenue -70%", impact="critical"
    )


def test_run_learning_cycle_full(db_session: Session) -> None:
    pid, uid = _project(db_session, "lsvc1")
    _seed_failing(db_session, pid)
    out = _svc().run_learning_cycle(db_session, pid, user_id=uid)
    assert out["experiences"]  # опыт собран
    assert any(p["pattern_type"] == "failure_pattern" for p in out["patterns"])
    assert out["improvements"]  # улучшения из провального паттерна
    assert out["insights"]


def test_learning_events_created_from_experience(db_session: Session) -> None:
    pid, _ = _project(db_session, "lsvc2")
    _seed_failing(db_session, pid)
    svc = _svc()
    svc.run_learning_cycle(db_session, pid)
    events = svc.get_history(db_session, pid)["events"]
    assert events and any(e["event_type"] == "failure" for e in events)


def test_explain_mentions_no_change(db_session: Session) -> None:
    pid, _ = _project(db_session, "lsvc3")
    _seed_failing(db_session, pid)
    svc = _svc()
    svc.run_learning_cycle(db_session, pid)
    insights = svc.explain_learning(db_session, pid)["insights"]
    joined = " ".join(insights).lower()
    assert "не меняются" in joined


def test_empty_project_cycle(db_session: Session) -> None:
    pid, _ = _project(db_session, "lsvc4")
    out = _svc().run_learning_cycle(db_session, pid)  # не падает
    assert out["experiences"] == [] and out["insights"]


def test_audit_lifecycle(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "lsvc5")
    _seed_failing(db_session, pid)
    _svc().run_learning_cycle(db_session, pid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "learning.experience_created",
        "learning.event_created",
        "learning.pattern_created",
        "learning.improvement_created",
    ):
        assert expected in actions
