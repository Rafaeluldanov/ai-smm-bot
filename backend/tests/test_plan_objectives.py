"""Тесты квартальных целей + вех — AI Business Planner (v0.7.7, offline).

Инварианты:
- 4 квартальные цели (Q1–Q4) с KPI (доля закрытия gap по кварталу, растёт к target);
- у каждой цели вехи; приоритеты заданы; повторная генерация пересоздаёт.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import business_planner_repository as repo
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import AIBusinessPlannerService

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


def _plan(db: Session, slug: str, target: float = 5000000, current: float = 1000000) -> int:
    pid, _ = _project(db, slug)
    svc = _svc()
    gid = svc.create_business_goal(
        db, pid, goal_type="revenue", title="Ц", target_value=target, current_value=current
    )["id"]
    return svc.generate_strategic_plan(db, gid)["plan"]["id"]


def test_four_quarters_in_order(db_session: Session) -> None:
    pid = _plan(db_session, "obj1")
    objectives = _svc().get_objectives(db_session, pid)
    assert [o["quarter"] for o in objectives] == ["Q1", "Q2", "Q3", "Q4"]
    assert all(o["priority"] in ("critical", "high", "medium", "low") for o in objectives)
    assert all(o["status"] == "planned" for o in objectives)


def test_kpi_targets_increase_toward_goal(db_session: Session) -> None:
    """KPI quarter_target растёт Q1→Q4 и в Q4 достигает target."""
    pid = _plan(db_session, "obj2", target=5000000, current=1000000)
    objectives = _svc().get_objectives(db_session, pid)
    targets = [o["kpi"][0]["quarter_target"] for o in objectives]
    assert targets == sorted(targets)  # монотонно растёт
    assert targets[0] == 2000000.0  # 1M + 4M*0.25
    assert targets[-1] == 5000000.0  # Q4 == target


def test_each_objective_has_milestones(db_session: Session) -> None:
    pid = _plan(db_session, "obj3")
    objectives = _svc().get_objectives(db_session, pid)
    for o in objectives:
        assert len(o["milestones"]) == 2
        assert all(m["status"] == "planned" for m in o["milestones"])


def test_regenerate_recreates_not_duplicates(db_session: Session) -> None:
    from app.models.plan_milestone import PlanMilestone

    pid = _plan(db_session, "obj4")
    svc = _svc()
    svc.generate_quarter_objectives(db_session, pid)
    svc.generate_quarter_objectives(db_session, pid)
    objectives = repo.list_objectives(db_session, pid)
    assert len(objectives) == 4  # цели не размножились
    # вехи тоже не «утекают»: ровно 2 на каждую цель (8 всего), без сирот от прошлых генераций.
    for o in objectives:
        assert len(repo.list_milestones(db_session, o.id)) == 2
    assert db_session.query(PlanMilestone).count() == 8


def test_objective_view_shape(db_session: Session) -> None:
    pid = _plan(db_session, "obj5")
    objective = repo.list_objectives(db_session, pid)[0]
    view = repo.public_objective_view(objective)
    for key in ("id", "plan_id", "quarter", "title", "kpi", "priority", "status"):
        assert key in view


def test_achieved_goal_holds_result(db_session: Session) -> None:
    """target <= current: KPI не растёт (убывает к target), стратегия — удержание результата."""
    ppid, _ = _project(db_session, "objhold")
    svc = _svc()
    gid = svc.create_business_goal(
        db_session, ppid, goal_type="revenue", title="Ц", target_value=500, current_value=1000
    )["id"]
    out = svc.generate_strategic_plan(db_session, gid)
    # gap_percent<=0 → ветка «удержание результата» в _build_strategy
    assert "удерж" in out["plan"]["strategy"]["approach"].lower()
    targets = [o["kpi"][0]["quarter_target"] for o in out["objectives"]]
    assert targets == sorted(targets, reverse=True)  # убывает current→target
    assert targets[-1] == 500.0  # Q4 == target
