"""Интеграция Calendar Assistant × AutopilotService (v0.5.8, offline).

Применённый календарь снимает блокер no_calendar и виден в дашборде автопилота; live-флаги
не меняются.
"""

from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.autopilot_calendar_assistant_service import (
    get_autopilot_calendar_assistant_service,
)
from app.services.autopilot_service import AutopilotService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def test_applied_calendar_clears_no_calendar_blocker(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cint-block")
    ap = AutopilotService()
    before = ap.run_health_check(db_session, project.id)
    assert any(b["type"] == "no_calendar" for b in before["blockers"])

    cal = get_autopilot_calendar_assistant_service()
    created = cal.create_calendar_plan(db_session, project.id, {"preset": "daily"}, dry_run=False)
    cal.apply_calendar_to_project(db_session, project.id, created["id"])

    after = ap.run_health_check(db_session, project.id)
    assert not any(b["type"] == "no_calendar" for b in after["blockers"])
    assert after["has_calendar"] is True


def test_dashboard_shows_calendar_assistant(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cint-dash")
    cal = get_autopilot_calendar_assistant_service()
    created = cal.create_calendar_plan(
        db_session, project.id, {"preset": "weekdays"}, dry_run=False
    )
    cal.apply_calendar_to_project(db_session, project.id, created["id"])

    dash = AutopilotService().build_autopilot_dashboard(db_session, project.id)
    assert "calendar_assistant" in dash
    assert dash["calendar_assistant"]["has_plan"] is True
    assert dash["calendar_assistant"]["preset"] == "weekdays"
