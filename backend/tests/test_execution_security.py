"""Тесты безопасности AI Execution Coordinator (v0.7.8, offline).

Жёсткие инварианты (Часть 18): запрещено выполнять задачи автоматически, менять бизнес, запускать
рекламу, менять деньги. Coordination-слой:
- generate/complete/assign НЕ публикуют, НЕ включают live, НЕ создают процессов;
- workflow-link ТОЛЬКО по подтверждению → лишь draft workflow (live off);
- бесплатно (0 units); секретов нет; tenant isolation; переживает падение смежных слоёв.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.business_workflow import BusinessWorkflow
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import AIBusinessPlannerService
from app.services.ai_execution_coordinator_service import (
    LINK_CONFIRMATION,
    AIExecutionCoordinatorError,
    AIExecutionCoordinatorService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_KEYS = ("token", "secret", "password", "api_key", "access_token", "refresh_token")


def _svc() -> AIExecutionCoordinatorService:
    return AIExecutionCoordinatorService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _generated(db: Session, pid: int) -> tuple[int, list[dict]]:
    pl = AIBusinessPlannerService(settings=_SETTINGS)
    gid = pl.create_business_goal(
        db, pid, goal_type="revenue", title="x5", target_value=5000000, current_value=1000000
    )["id"]
    sp = pl.generate_strategic_plan(db, gid)["plan"]["id"]
    pl.approve_plan(db, sp)
    svc = _svc()
    ep = svc.create_execution_plan(db, pid, strategic_plan_id=sp)["id"]
    out = svc.generate_execution(db, ep)
    tasks = [t for o in out["objectives"] for t in o["tasks"]]
    return ep, tasks


def test_billing_is_free() -> None:
    from app.services.billing_service import (
        ACTION_COSTS,
        USAGE_EXECUTION_PLAN,
        USAGE_EXECUTION_REPORT,
    )

    assert ACTION_COSTS[USAGE_EXECUTION_PLAN] == 0
    assert ACTION_COSTS[USAGE_EXECUTION_REPORT] == 0


def test_generate_and_complete_do_not_publish_or_run(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsec1")
    ep, tasks = _generated(db_session, pid)
    svc = _svc()
    svc.complete_task(db_session, tasks[0]["id"])
    # generate/complete НЕ создают процессов и НЕ публикуют.
    assert db_session.query(BusinessWorkflow).filter_by(project_id=pid).count() == 0
    assert db_session.query(PostPublication).count() == 0


def test_workflow_link_requires_confirmation(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsec2")
    _ep, tasks = _generated(db_session, pid)
    with pytest.raises(AIExecutionCoordinatorError):
        _svc().create_workflow_link(db_session, tasks[0]["id"], confirmation="")


def test_workflow_link_creates_only_draft(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsec3")
    _ep, tasks = _generated(db_session, pid)
    res = _svc().create_workflow_link(db_session, tasks[0]["id"], confirmation=LINK_CONFIRMATION)
    assert res["live_enabled"] is False
    wfs = db_session.query(BusinessWorkflow).filter_by(project_id=pid).all()
    assert len(wfs) == 1 and wfs[0].status == "draft"
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_assign_foreign_owner_blocked(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsec4")
    _pid2, uid2 = _project(db_session, "exsec4b")
    _ep, tasks = _generated(db_session, pid)
    with pytest.raises(AIExecutionCoordinatorError):
        _svc().assign_owner(db_session, tasks[0]["id"], uid2)


def test_assign_fails_closed_on_check_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если проверка доступа владельца падает — назначение НЕ проходит (fail closed)."""
    pid, uid = _project(db_session, "exsec4c")
    _ep, tasks = _generated(db_session, pid)

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("acl down")

    monkeypatch.setattr("app.services.saas_security_service.user_can_access_account", _boom)
    with pytest.raises(AIExecutionCoordinatorError):
        _svc().assign_owner(db_session, tasks[0]["id"], uid)
    # владелец НЕ назначен (fail closed)
    from app.repositories import execution_repository as repo

    assert repo.get_task(db_session, tasks[0]["id"]).owner_user_id is None


def test_public_views_have_no_secrets(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsec5")
    ep, _tasks = _generated(db_session, pid)
    svc = _svc()
    blob = (
        str(svc.get_execution_plan(db_session, ep)) + str(svc.get_health(db_session, ep))
    ).lower()
    for key in _SECRET_KEYS:
        assert key not in blob


def test_cross_tenant_plan_isolated(db_session: Session) -> None:
    pid1, _ = _project(db_session, "exsec6a")
    _pid2, _ = _project(db_session, "exsec6b")
    ep, _tasks = _generated(db_session, pid1)
    assert _svc().get_execution_plan(db_session, ep)["plan"]["project_id"] == pid1


def test_generate_survives_missing_layers(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Падение planner/chief слоёв НЕ роняет координацию (health/recommendations)."""
    pid, _ = _project(db_session, "exsec7")
    ep, _tasks = _generated(db_session, pid)

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("layer down")

    monkeypatch.setattr("app.repositories.business_planner_repository.list_objectives", _boom)
    monkeypatch.setattr(
        "app.services.ai_chief_of_staff_service.AIChiefOfStaffService.build_decision_context",
        _boom,
    )
    # health/recommendations не падают несмотря на сбои смежных слоёв.
    health = _svc().get_health(db_session, ep)
    assert "recommendations" in health and health["recommendations"]
