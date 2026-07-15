"""Тесты бизнес-целей + gap-анализ — AI Business Planner (v0.7.7, offline).

Инварианты:
- goal создаётся; gap = target − current; current подтягивается из baseline при 0;
- неизвестный тип/пустое название отклоняются; tenant/summary; аудит goal.created.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import (
    AIBusinessPlannerError,
    AIBusinessPlannerService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIBusinessPlannerService:
    return AIBusinessPlannerService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def test_create_goal(db_session: Session) -> None:
    pid, uid = _project(db_session, "goal1")
    g = _svc().create_business_goal(
        db_session,
        pid,
        goal_type="revenue",
        title="Выручка x5",
        target_value=5000000,
        current_value=1000000,
        user_id=uid,
    )
    assert g["goal_type"] == "revenue" and g["status"] == "active"
    assert g["gap"] == 4000000.0


def test_create_rejects_unknown_type(db_session: Session) -> None:
    pid, _ = _project(db_session, "goal2")
    with pytest.raises(AIBusinessPlannerError):
        _svc().create_business_goal(db_session, pid, goal_type="bogus", title="x")


def test_create_rejects_empty_title(db_session: Session) -> None:
    pid, _ = _project(db_session, "goal2b")
    with pytest.raises(AIBusinessPlannerError):
        _svc().create_business_goal(db_session, pid, goal_type="revenue", title="   ")


def test_gap_computed(db_session: Session) -> None:
    pid, _ = _project(db_session, "goal3")
    svc = _svc()
    g = svc.create_business_goal(
        db_session, pid, goal_type="revenue", title="Рост", target_value=1000, current_value=250
    )
    gap = svc.analyze_gap(db_session, g["id"])
    assert gap["current"] == 250.0 and gap["target"] == 1000.0
    assert gap["gap"] == 750.0 and gap["gap_percent"] == 75.0
    assert gap["metric"] == "revenue"


def test_gap_current_from_baseline_when_zero(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если current_value=0, current подтягивается из Business Forecasting baseline."""
    pid, _ = _project(db_session, "goal4")
    monkeypatch.setattr(
        "app.services.ai_business_forecasting_service.AIBusinessForecastingService.collect_business_baseline",
        lambda *_a, **_k: {"revenue": 300.0, "_meta": {"sources_with_data": 1, "sources_total": 3}},
    )
    svc = _svc()
    g = svc.create_business_goal(
        db_session, pid, goal_type="revenue", title="Рост", target_value=1000, current_value=0
    )
    gap = svc.analyze_gap(db_session, g["id"])
    assert gap["current"] == 300.0  # из baseline
    assert gap["gap"] == 700.0


def test_gap_survives_raising_baseline(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """current=0 + падение baseline-слоя → gap не роняется (fallback current=0.0)."""
    pid, _ = _project(db_session, "goal4b")

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("layer down")

    monkeypatch.setattr(
        "app.services.ai_business_forecasting_service.AIBusinessForecastingService.collect_business_baseline",
        _boom,
    )
    svc = _svc()
    g = svc.create_business_goal(
        db_session, pid, goal_type="revenue", title="Рост", target_value=1000, current_value=0
    )
    gap = svc.analyze_gap(db_session, g["id"])  # не падает
    assert gap["current"] == 0.0 and gap["gap"] == 1000.0


def test_list_and_summary(db_session: Session) -> None:
    pid, _ = _project(db_session, "goal5")
    svc = _svc()
    svc.create_business_goal(db_session, pid, goal_type="growth", title="A", target_value=10)
    svc.create_business_goal(db_session, pid, goal_type="sales", title="B", target_value=20)
    assert len(svc.list_goals(db_session, pid)) == 2
    summary = svc.get_summary(db_session, pid)
    assert summary["goals_total"] == 2 and summary["goals_active"] == 2


def test_audit_goal_created(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "goal6")
    _svc().create_business_goal(
        db_session, pid, goal_type="revenue", title="Ц", target_value=1, user_id=uid
    )
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "goal.created" in actions


def test_missing_goal_raises_not_found(db_session: Session) -> None:
    with pytest.raises(AIBusinessPlannerError, match="не найден"):
        _svc().analyze_gap(db_session, 999999)


def test_missing_project_raises_not_found(db_session: Session) -> None:
    with pytest.raises(AIBusinessPlannerError, match="не найден"):
        _svc().create_business_goal(db_session, 999999, goal_type="revenue", title="x")
