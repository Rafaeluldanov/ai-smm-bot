"""Тесты оценки и приоритизации — AI Autonomous Optimization (v0.8.1, offline).

Инварианты:
- Optimization Score = impact × confidence − cost − risk (confidence как доля), clamp 0..100;
- приоритет по порогам score; prioritize ранжирует critical→low и переоценивает приоритет.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import optimization_repository as repo
from app.schemas.project import ProjectCreate
from app.services.ai_optimization_engine_service import AIOptimizationEngineService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIOptimizationEngineService:
    return AIOptimizationEngineService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def test_score_formula() -> None:
    svc = _svc()
    # 80 × (90/100) − 10 − 10 = 72 − 20 = 52.0
    assert svc.calculate_optimization_score(80, 90, 10, 10) == 52.0
    # 100 × 1 − 0 − 0 = 100
    assert svc.calculate_optimization_score(100, 100, 0, 0) == 100.0


def test_score_clamped_to_zero() -> None:
    svc = _svc()
    # 30 × 0.5 − 40 − 40 = 15 − 80 = −65 → clamp 0
    assert svc.calculate_optimization_score(30, 50, 40, 40) == 0.0


def test_score_never_exceeds_100() -> None:
    svc = _svc()
    assert svc.calculate_optimization_score(100, 100, 0, 0) <= 100.0


def test_priority_thresholds() -> None:
    svc = _svc()
    assert svc._priority_from_score(75.0) == "critical"
    assert svc._priority_from_score(74.9) == "high"
    assert svc._priority_from_score(50.0) == "high"
    assert svc._priority_from_score(49.9) == "medium"
    assert svc._priority_from_score(25.0) == "medium"
    assert svc._priority_from_score(24.9) == "low"
    assert svc._priority_from_score(0.0) == "low"


def test_prioritize_orders_critical_first(db_session: Session) -> None:
    pid = _project(db_session, "sc1")
    repo.create_optimization(
        db_session,
        project_id=pid,
        account_id=None,
        title="low",
        optimization_score=10.0,
        priority="low",
    )
    repo.create_optimization(
        db_session,
        project_id=pid,
        account_id=None,
        title="crit",
        optimization_score=90.0,
        priority="critical",
    )
    ranked = _svc().prioritize_improvements(db_session, pid)
    assert ranked[0]["priority"] == "critical"
    assert ranked[-1]["priority"] == "low"


def test_prioritize_recomputes_priority(db_session: Session) -> None:
    """Приоритет переоценивается из score (если рассинхронизирован)."""
    pid = _project(db_session, "sc2")
    opt = repo.create_optimization(
        db_session,
        project_id=pid,
        account_id=None,
        title="mismatch",
        optimization_score=80.0,
        priority="low",  # намеренно неверный приоритет
    )
    _svc().prioritize_improvements(db_session, pid)
    db_session.refresh(opt)
    assert opt.priority == "critical"  # 80 → critical
