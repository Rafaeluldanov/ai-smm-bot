"""Тесты AIOptimizationGovernanceService — цикл governance (v0.8.2, offline).

Инварианты:
- run_governance_cycle заводит governance по оптимизациям (идемпотентно); portfolio-метрики;
- explain; аудит; НЕ утверждает автоматически и НЕ меняет бизнес.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import optimization_repository as opt_repo
from app.schemas.project import ProjectCreate
from app.services.ai_optimization_governance_service import AIOptimizationGovernanceService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIOptimizationGovernanceService:
    return AIOptimizationGovernanceService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id, account.id


def _optimization(db: Session, pid: int, aid: int, *, priority: str = "high") -> int:
    opt = opt_repo.create_optimization(
        db,
        project_id=pid,
        account_id=aid,
        title="Ускорить исполнение",
        optimization_score=60.0,
        priority=priority,
    )
    return opt.id


def test_create_governance_from_optimization(db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "gs1")
    oid = _optimization(db_session, pid, aid)
    out = _svc().run_governance_cycle(db_session, pid, user_id=uid)
    assert len(out["created"]) == 1
    g = out["governances"][0]
    assert g["optimization_id"] == oid
    assert g["status"] == "identified" and g["approval_status"] == "pending"


def test_cycle_idempotent(db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "gs2")
    _optimization(db_session, pid, aid)
    svc = _svc()
    svc.run_governance_cycle(db_session, pid)
    second = svc.run_governance_cycle(db_session, pid)
    assert second["created"] == []
    assert len(second["governances"]) == 1


def test_empty_project_cycle(db_session: Session) -> None:
    pid, _, _ = _project(db_session, "gs3")
    out = _svc().run_governance_cycle(db_session, pid)  # не падает
    assert out["created"] == [] and out["governances"] == [] and out["insights"]


def test_portfolio_metrics(db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "gs4")
    _optimization(db_session, pid, aid)
    svc = _svc()
    svc.run_governance_cycle(db_session, pid, user_id=uid)
    pm = svc.calculate_portfolio_metrics(db_session, pid)
    assert pm["total"] == 1 and pm["pending"] == 1 and pm["approved"] == 0


def test_explain_no_change(db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "gs5")
    _optimization(db_session, pid, aid)
    svc = _svc()
    svc.run_governance_cycle(db_session, pid, user_id=uid)
    insights = svc.explain_governance(db_session, pid)["insights"]
    joined = " ".join(insights).lower()
    assert "не меняются" in joined


def test_audit_created(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid, aid = _project(db_session, "gs6")
    _optimization(db_session, pid, aid)
    _svc().run_governance_cycle(db_session, pid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "governance.created" in actions
