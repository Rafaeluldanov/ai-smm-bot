"""Тесты CLI Calendar Assistant (v0.5.8). Offline; dry-run без записи; без секретов."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models.autopilot_calendar_plan import AutopilotCalendarPlan
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.scripts import (
    autopilot_calendar_apply,
    autopilot_calendar_create,
    autopilot_calendar_dashboard,
    autopilot_calendar_preview,
)


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="П", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def test_scripts_import() -> None:
    assert callable(autopilot_calendar_preview.main)
    assert callable(autopilot_calendar_create.main)
    assert callable(autopilot_calendar_apply.main)
    assert callable(autopilot_calendar_dashboard.main)


def test_preview_cli_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "cacli-pv")
    before = db_session.query(AutopilotCalendarPlan).count()
    monkeypatch.setattr(autopilot_calendar_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "autopilot_calendar_preview",
            "--project-id",
            str(project.id),
            "--preset",
            "three_per_week",
        ],
    )
    autopilot_calendar_preview.main()
    out = capsys.readouterr().out
    assert "posts_per_month:" in out
    assert "writes:          False" in out
    assert db_session.query(AutopilotCalendarPlan).count() == before


def test_create_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "cacli-dry")
    before = db_session.query(AutopilotCalendarPlan).count()
    monkeypatch.setattr(autopilot_calendar_create, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["autopilot_calendar_create", "--project-id", str(project.id), "--dry-run", "true"],
    )
    autopilot_calendar_create.main()
    out = capsys.readouterr().out
    assert "dry_run:         True" in out
    assert db_session.query(AutopilotCalendarPlan).count() == before


def test_create_and_apply_cli(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "cacli-apply")
    monkeypatch.setattr(autopilot_calendar_create, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "autopilot_calendar_create",
            "--project-id",
            str(project.id),
            "--preset",
            "daily",
            "--dry-run",
            "false",
        ],
    )
    autopilot_calendar_create.main()
    out = capsys.readouterr().out
    plan = db_session.query(AutopilotCalendarPlan).first()
    assert plan is not None
    assert f"calendar_plan_id: {plan.id}" in out

    monkeypatch.setattr(autopilot_calendar_apply, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "autopilot_calendar_apply",
            "--project-id",
            str(project.id),
            "--calendar-plan-id",
            str(plan.id),
        ],
    )
    autopilot_calendar_apply.main()
    out = capsys.readouterr().out
    assert "live_publish:       False" in out


def test_dashboard_cli(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "cacli-dash")
    monkeypatch.setattr(autopilot_calendar_dashboard, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["autopilot_calendar_dashboard", "--project-id", str(project.id)]
    )
    autopilot_calendar_dashboard.main()
    out = capsys.readouterr().out
    assert "has_active_plan:" in out
