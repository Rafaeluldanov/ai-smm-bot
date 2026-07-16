"""Тесты обнаружения паттернов + причин провалов — AI Continuous Improvement (v0.8.0, offline).

Инварианты:
- ≥2 success → success_pattern; ≥1 failure → failure_pattern; блокеры/отклонения → optimization;
- analyze_failure находит причины (стратегия/прогноз/исполнение/ресурсы).
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import continuous_improvement_repository as repo
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


def _exp(db: Session, pid: int, outcome: str, title: str) -> None:
    repo.create_experience(
        db,
        project_id=pid,
        account_id=None,
        experience_type="performance",
        title=title,
        outcome=outcome,
    )


def test_success_pattern_from_two_successes(db_session: Session) -> None:
    pid, _ = _project(db_session, "pat1")
    _exp(db_session, pid, "success", "Успех A")
    _exp(db_session, pid, "success", "Успех B")
    patterns = _svc().detect_patterns(db_session, pid)
    assert any(p["pattern_type"] == "success_pattern" for p in patterns)


def test_single_success_no_pattern(db_session: Session) -> None:
    """Один успех недостаточен для success_pattern (нужно ≥2)."""
    pid, _ = _project(db_session, "pat2")
    _exp(db_session, pid, "success", "Успех")
    patterns = _svc().detect_patterns(db_session, pid)
    assert not any(p["pattern_type"] == "success_pattern" for p in patterns)


def test_failure_pattern_from_failure(db_session: Session) -> None:
    pid, _ = _project(db_session, "pat3")
    _exp(db_session, pid, "failure", "Провал")
    patterns = _svc().detect_patterns(db_session, pid)
    fail = [p for p in patterns if p["pattern_type"] == "failure_pattern"]
    assert fail and fail[0]["confidence_score"] > 0


def test_optimization_pattern_from_deviations(db_session: Session) -> None:
    pid, _ = _project(db_session, "pat4")
    snap = perf_repo.create_snapshot(
        db_session, project_id=pid, account_id=None, status="warning", performance_score=50.0
    )
    perf_repo.create_deviation(
        db_session, snapshot_id=snap.id, metric="leads", title="leads -20%", impact="medium"
    )
    patterns = _svc().detect_patterns(db_session, pid)
    assert any(p["pattern_type"] == "optimization_pattern" for p in patterns)


def test_analyze_failure_execution_causes(db_session: Session) -> None:
    """analyze_failure находит причины исполнения (блокеры / нет владельцев)."""
    from app.repositories import execution_repository as exec_repo

    pid, _ = _project(db_session, "pat5")
    plan = exec_repo.create_execution_plan(
        db_session, project_id=pid, account_id=None, title="План", status="active"
    )
    objective = exec_repo.create_objective(db_session, execution_plan_id=plan.id, title="Цель")
    exec_repo.create_task(db_session, objective_id=objective.id, title="Задача", status="blocked")
    causes = _svc().analyze_failure(db_session, pid)
    joined = " ".join(causes).lower()
    assert "блокер" in joined or "владельц" in joined


def test_analyze_failure_forecast_cause(db_session: Session) -> None:
    """Низкая уверенность прогноза → причина «плохой прогноз»."""
    from app.repositories import business_forecast_repository as fc_repo

    pid, _ = _project(db_session, "pat6")
    fc_repo.create_forecast(
        db_session, project_id=pid, account_id=None, title="Прогноз", confidence_score=20.0
    )
    causes = _svc().analyze_failure(db_session, pid)
    assert any("прогноз" in c.lower() for c in causes)


def test_no_experience_no_patterns(db_session: Session) -> None:
    pid, _ = _project(db_session, "pat7")
    assert _svc().detect_patterns(db_session, pid) == []
