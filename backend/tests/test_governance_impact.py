"""Тесты impact tracking — AI Optimization Governance (v0.8.2, offline).

Инварианты:
- track_impact выводит статус/score из ExperimentResult (positive/negative/neutral/measuring);
- цикл авто-создаёт impact при завершённом эксперименте; portfolio отражает impact; аудит.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import optimization_governance_repository as gov_repo
from app.repositories import optimization_repository as opt_repo
from app.schemas.project import ProjectCreate
from app.services.ai_optimization_governance_service import AIOptimizationGovernanceService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIOptimizationGovernanceService:
    return AIOptimizationGovernanceService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, account.id


def _governance_with_result(
    db: Session, slug: str, *, validation: str | None, with_experiment: bool = True
) -> int:
    pid, aid = _project(db, slug)
    opt = opt_repo.create_optimization(
        db, project_id=pid, account_id=aid, title="opt", optimization_score=60.0, priority="high"
    )
    if with_experiment:
        exp = opt_repo.create_experiment(
            db,
            optimization_id=opt.id,
            title="e",
            metric="execution_speed",
            baseline_value=50.0,
            target_value=60.0,
            status="completed",
        )
        if validation is not None:
            opt_repo.create_result(
                db,
                experiment_id=exp.id,
                actual_value=65.0,
                expected_value=60.0,
                difference=5.0,
                validation_result=validation,
                analysis={},
            )
    governance = gov_repo.create_governance(
        db, project_id=pid, account_id=aid, optimization_id=opt.id
    )
    return governance.id


def test_track_impact_positive(db_session: Session) -> None:
    gid = _governance_with_result(db_session, "gi1", validation="success")
    out = _svc().track_impact(db_session, gid)
    assert out["status"] == "positive" and out["impact_score"] == 60.0


def test_track_impact_negative(db_session: Session) -> None:
    gid = _governance_with_result(db_session, "gi2", validation="failure")
    out = _svc().track_impact(db_session, gid)
    assert out["status"] == "negative" and out["impact_score"] == 0.0


def test_track_impact_neutral(db_session: Session) -> None:
    gid = _governance_with_result(db_session, "gi3", validation="inconclusive")
    out = _svc().track_impact(db_session, gid)
    assert out["status"] == "neutral" and out["impact_score"] == 30.0  # 60 / 2


def test_track_impact_measuring(db_session: Session) -> None:
    """Завершённый эксперимент без результата → measuring."""
    gid = _governance_with_result(db_session, "gi4", validation=None)
    out = _svc().track_impact(db_session, gid)
    assert out["status"] == "measuring"


def test_track_impact_unknown(db_session: Session) -> None:
    """Нет эксперимента → unknown."""
    gid = _governance_with_result(db_session, "gi5", validation=None, with_experiment=False)
    out = _svc().track_impact(db_session, gid)
    assert out["status"] == "unknown"


def test_cycle_auto_creates_impact(db_session: Session) -> None:
    """run_governance_cycle авто-создаёт impact при завершённом эксперименте."""
    pid, aid = _project(db_session, "gi6")
    opt = opt_repo.create_optimization(
        db_session, project_id=pid, account_id=aid, title="opt", optimization_score=60.0
    )
    exp = opt_repo.create_experiment(
        db_session,
        optimization_id=opt.id,
        title="e",
        metric="m",
        baseline_value=50.0,
        target_value=60.0,
        status="completed",
    )
    opt_repo.create_result(
        db_session,
        experiment_id=exp.id,
        actual_value=65.0,
        expected_value=60.0,
        difference=5.0,
        validation_result="success",
        analysis={},
    )
    svc = _svc()
    svc.run_governance_cycle(db_session, pid)
    pm = svc.calculate_portfolio_metrics(db_session, pid)
    assert pm["avg_impact_score"] == 60.0 and pm["positive_impacts"] == 1


def test_cycle_impact_idempotent(db_session: Session) -> None:
    """Повторный цикл НЕ дублирует impact (guard get_latest_impact)."""
    pid, aid = _project(db_session, "gi8")
    opt = opt_repo.create_optimization(
        db_session, project_id=pid, account_id=aid, title="opt", optimization_score=60.0
    )
    exp = opt_repo.create_experiment(
        db_session,
        optimization_id=opt.id,
        title="e",
        metric="m",
        baseline_value=50.0,
        target_value=60.0,
        status="completed",
    )
    opt_repo.create_result(
        db_session,
        experiment_id=exp.id,
        actual_value=65.0,
        expected_value=60.0,
        difference=5.0,
        validation_result="success",
        analysis={},
    )
    svc = _svc()
    out = svc.run_governance_cycle(db_session, pid)
    svc.run_governance_cycle(db_session, pid)  # второй прогон
    pm = svc.calculate_portfolio_metrics(db_session, pid)
    assert pm["positive_impacts"] == 1 and pm["avg_impact_score"] == 60.0
    gid = out["governances"][0]["id"]
    assert len(gov_repo.list_impacts(db_session, gid)) == 1  # ровно один impact


def test_lifecycle_active_completed(db_session: Session) -> None:
    """approve → assign_owner (active) → track_impact (completed); portfolio отражает статусы."""
    owner = user_repository.create_user(db_session, email="lc@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="lc", slug="lc", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="lc", slug="lc"))
    project.account_id = account.id
    db_session.commit()
    pid, aid, uid = project.id, account.id, owner.id
    opt = opt_repo.create_optimization(
        db_session, project_id=pid, account_id=aid, title="opt", optimization_score=60.0
    )
    exp = opt_repo.create_experiment(
        db_session,
        optimization_id=opt.id,
        title="e",
        metric="m",
        baseline_value=50.0,
        target_value=60.0,
        status="completed",
    )
    opt_repo.create_result(
        db_session,
        experiment_id=exp.id,
        actual_value=65.0,
        expected_value=60.0,
        difference=5.0,
        validation_result="success",
        analysis={},
    )
    governance = gov_repo.create_governance(
        db_session, project_id=pid, account_id=aid, optimization_id=opt.id
    )
    svc = _svc()
    svc.approve_optimization(db_session, governance.id, user_id=uid)
    svc.assign_owner(db_session, governance.id, uid, user_id=uid)
    db_session.refresh(governance)
    assert governance.status == "active"  # approved + owner → active
    svc.track_impact(db_session, governance.id, user_id=uid)
    db_session.refresh(governance)
    assert governance.status == "completed"  # measured impact → completed
    pm = svc.calculate_portfolio_metrics(db_session, pid)
    assert pm["completed"] == 1 and pm["active"] == 0


def test_audit_impact_updated(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    gid = _governance_with_result(db_session, "gi7", validation="success")
    _svc().track_impact(db_session, gid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "governance.impact_updated" in actions
