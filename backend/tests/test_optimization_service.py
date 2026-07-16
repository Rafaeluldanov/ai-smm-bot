"""Тесты AIOptimizationEngineService — цикл оптимизации (v0.8.1, offline).

Инварианты:
- run_optimization_cycle: Improvement Backlog → создаёт/оценивает/приоритизирует оптимизации;
- идемпотентность; learning feedback → LearningEvent; explain; аудит; НЕ меняет бизнес.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import continuous_improvement_repository as ci_repo
from app.schemas.project import ProjectCreate
from app.services.ai_optimization_engine_service import AIOptimizationEngineService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIOptimizationEngineService:
    return AIOptimizationEngineService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _seed_improvement(
    db: Session, pid: int, *, title: str = "Снять блокеры и зависимости", priority: str = "high"
) -> int:
    imp = ci_repo.create_improvement(
        db,
        project_id=pid,
        account_id=None,
        title=title,
        priority=priority,
        description="уменьшить зависимости",
    )
    return imp.id


def test_create_optimization_from_improvement(db_session: Session) -> None:
    pid, uid = _project(db_session, "os1")
    _seed_improvement(db_session, pid)
    out = _svc().run_optimization_cycle(db_session, pid, user_id=uid)
    assert len(out["created"]) == 1
    opt = out["optimizations"][0]
    assert opt["optimization_score"] >= 0.0
    assert opt["priority"] in ("critical", "high", "medium", "low")
    assert opt["status"] == "identified"


def test_cycle_idempotent(db_session: Session) -> None:
    pid, _ = _project(db_session, "os2")
    _seed_improvement(db_session, pid)
    svc = _svc()
    svc.run_optimization_cycle(db_session, pid)
    second = svc.run_optimization_cycle(db_session, pid)
    assert second["created"] == []  # уже оценено — не дублируем
    assert len(second["optimizations"]) == 1


def test_empty_project_cycle(db_session: Session) -> None:
    pid, _ = _project(db_session, "os3")
    out = _svc().run_optimization_cycle(db_session, pid)  # не падает
    assert out["created"] == [] and out["optimizations"] == [] and out["insights"]


def test_learning_feedback_creates_event(db_session: Session) -> None:
    pid, uid = _project(db_session, "os4")
    _seed_improvement(db_session, pid)
    svc = _svc()
    opt = svc.run_optimization_cycle(db_session, pid, user_id=uid)["optimizations"][0]
    exp = svc.create_experiment(db_session, opt["id"], user_id=uid)
    out = svc.validate_experiment(
        db_session, exp["id"], actual_value=exp["target_value"] + 5, user_id=uid
    )
    assert out["learning_feedback"] is not None
    events = ci_repo.list_events(db_session, pid)
    assert events and events[0].event_type == "success"


def test_only_actionable_improvements_optimized(db_session: Session) -> None:
    """rejected/completed улучшения не оптимизируются."""
    pid, _ = _project(db_session, "os5")
    imp = ci_repo.create_improvement(
        db_session, project_id=pid, account_id=None, title="Отклонённое", priority="high"
    )
    ci_repo.update_improvement(db_session, imp, status="rejected")
    out = _svc().run_optimization_cycle(db_session, pid)
    assert out["created"] == []


def test_explain_first_choice(db_session: Session) -> None:
    pid, _ = _project(db_session, "os6")
    _seed_improvement(db_session, pid)
    svc = _svc()
    svc.run_optimization_cycle(db_session, pid)
    insights = svc.explain_optimization(db_session, pid)["insights"]
    joined = " ".join(insights).lower()
    assert "первым выбрано" in joined
    assert "не меняются" in joined


def test_audit_lifecycle(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "os7")
    _seed_improvement(db_session, pid)
    _svc().run_optimization_cycle(db_session, pid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "optimization.created" in actions
    assert "optimization.prioritized" in actions
