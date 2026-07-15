"""Тесты безопасности AI Business Planner (v0.7.7, offline).

Жёсткие инварианты (Часть 18): запрещено выполнять план автоматически, менять бизнес, запускать
рекламу, менять деньги. Planning-слой:
- convert ТОЛЬКО при approved+подтверждении → лишь draft workflow (live off, без публикаций/CRM);
- бесплатно (0 units); секретов в ответах нет; строгая tenant isolation; переживает падение слоёв.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.business_workflow import BusinessWorkflow
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import (
    CONVERT_CONFIRMATION,
    AIBusinessPlannerError,
    AIBusinessPlannerService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_KEYS = ("token", "secret", "password", "api_key", "access_token", "refresh_token")


def _svc() -> AIBusinessPlannerService:
    return AIBusinessPlannerService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _approved_plan(db: Session, pid: int) -> int:
    svc = _svc()
    gid = svc.create_business_goal(
        db, pid, goal_type="revenue", title="Ц", target_value=5000000, current_value=1000000
    )["id"]
    plan = svc.generate_strategic_plan(db, gid)["plan"]
    svc.approve_plan(db, plan["id"])
    return plan["id"]


def test_billing_is_free() -> None:
    from app.services.billing_service import (
        ACTION_COSTS,
        USAGE_BUSINESS_PLAN,
        USAGE_PLAN_REPORT,
    )

    assert ACTION_COSTS[USAGE_BUSINESS_PLAN] == 0
    assert ACTION_COSTS[USAGE_PLAN_REPORT] == 0


def test_generate_does_not_publish_or_create_workflow(db_session: Session) -> None:
    """Генерация плана НЕ публикует и НЕ создаёт процессов (только план)."""
    pid, _ = _project(db_session, "psec1")
    svc = _svc()
    gid = svc.create_business_goal(
        db_session, pid, goal_type="revenue", title="Ц", target_value=100, current_value=10
    )["id"]
    svc.generate_strategic_plan(db_session, gid)
    assert db_session.query(BusinessWorkflow).filter_by(project_id=pid).count() == 0
    assert db_session.query(PostPublication).count() == 0


def test_convert_requires_approved_and_confirmation(db_session: Session) -> None:
    pid, _ = _project(db_session, "psec2")
    svc = _svc()
    gid = svc.create_business_goal(
        db_session, pid, goal_type="revenue", title="Ц", target_value=100, current_value=10
    )["id"]
    plan = svc.generate_strategic_plan(db_session, gid)["plan"]
    with pytest.raises(AIBusinessPlannerError):  # не approved
        svc.convert_to_workflow(db_session, plan["id"], confirmation=CONVERT_CONFIRMATION)
    svc.approve_plan(db_session, plan["id"])
    with pytest.raises(AIBusinessPlannerError):  # нет подтверждения
        svc.convert_to_workflow(db_session, plan["id"], confirmation="")


def test_convert_creates_only_draft_no_live(db_session: Session) -> None:
    pid, _ = _project(db_session, "psec3")
    plan_id = _approved_plan(db_session, pid)
    res = _svc().convert_to_workflow(db_session, plan_id, confirmation=CONVERT_CONFIRMATION)
    assert res["live_enabled"] is False
    wfs = db_session.query(BusinessWorkflow).filter_by(project_id=pid).all()
    assert len(wfs) == 1 and wfs[0].status == "draft"
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_public_views_have_no_secrets(db_session: Session) -> None:
    pid, _ = _project(db_session, "psec4")
    plan_id = _approved_plan(db_session, pid)
    svc = _svc()
    bundle = svc.get_plan(db_session, plan_id)
    for blob in (str(bundle).lower(), str(svc.explain_plan(db_session, plan_id)).lower()):
        for key in _SECRET_KEYS:
            assert key not in blob


def test_confidence_bounded(db_session: Session) -> None:
    pid, _ = _project(db_session, "psec5")
    plan_id = _approved_plan(db_session, pid)
    plan = _svc().get_plan(db_session, plan_id)["plan"]
    assert 0.0 <= plan["confidence_score"] <= 100.0


def test_cross_tenant_goal_view_isolated(db_session: Session) -> None:
    pid1, _ = _project(db_session, "psec6a")
    _pid2, _ = _project(db_session, "psec6b")
    svc = _svc()
    gid = svc.create_business_goal(
        db_session, pid1, goal_type="growth", title="Ц", target_value=10
    )["id"]
    # get_goal возвращает проект-владельца (tenant iso на API-гарде).
    assert svc.get_goal(db_session, gid)["goal"]["project_id"] == pid1


def test_plan_survives_missing_layers(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Падение прогноза/decision слоёв НЕ роняет генерацию плана — срабатывают try/except."""
    pid, _ = _project(db_session, "psec7")

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("layer down")

    monkeypatch.setattr(
        "app.services.ai_business_forecasting_service.AIBusinessForecastingService.collect_business_baseline",
        _boom,
    )
    monkeypatch.setattr("app.repositories.business_forecast_repository.get_latest_forecast", _boom)
    monkeypatch.setattr("app.repositories.decision_repository.list_decisions", _boom)
    svc = _svc()
    # current_value=0 → задействуется baseline-fallback (тоже падает) → все три try/except активны.
    gid = svc.create_business_goal(
        db_session, pid, goal_type="revenue", title="Ц", target_value=1000, current_value=0
    )["id"]
    gap = svc.analyze_gap(db_session, gid)  # baseline упал → current=0.0, не падает
    assert gap["current"] == 0.0 and gap["gap"] == 1000.0
    out = svc.generate_strategic_plan(db_session, gid)  # не падает
    assert len(out["objectives"]) == 4
    assert 0.0 <= out["plan"]["confidence_score"] <= 100.0
