"""Тесты CLI движка расписаний: preview печатает due, run dry-run по умолчанию."""

from sqlalchemy.orm import Session, sessionmaker

from app.repositories import account_repository, project_repository, user_repository
from app.repositories import crm_bot_smm_repository as crm
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.project import ProjectCreate
from app.scripts import schedule_due_preview as preview_cli
from app.scripts import schedule_due_run as run_cli
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_MONDAY = "2026-07-13"


def _seed(db: Session) -> tuple[int, int]:
    user = user_repository.create_user(db, email="cli@e.com", password_hash="x")
    account = account_repository.create_account(db, name="A", slug="teeon", owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    project.account_id = account.id
    db.commit()
    config = crm.create_config(
        db, CrmBotProjectConfigCreate(project_id=project.id, display_name="T")
    )
    category = crm.create_category(
        db, CrmPromotionCategoryCreate(project_id=project.id, config_id=config.id, title="C")
    )
    crm.create_plan(
        db,
        CrmPublishingPlanCreate(
            project_id=project.id,
            config_id=config.id,
            category_id=category.id,
            weekdays=[0],
            publish_times=["12:00"],
            platforms=["telegram"],
        ),
    )
    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@x"}
    )
    BillingService().manual_topup(db, account.id, 500, idempotency_key="seed")
    db.commit()
    return account.id, project.id


def test_preview_prints_due(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    account_id, project_id = _seed(db_session)
    monkeypatch.setattr(preview_cli, "get_sessionmaker", lambda: session_factory)
    code = preview_cli.main(
        [
            "--account-id",
            str(account_id),
            "--project-id",
            str(project_id),
            "--platform",
            "telegram",
            "--date",
            _MONDAY,
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "due-задач: 1" in out
    assert "would_create_draft" in out
    assert "live-публикация: выключена" in out
    assert _TOKEN not in out


def test_run_dry_run_default_no_writes(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    account_id, project_id = _seed(db_session)
    from app.models.schedule_run import ScheduleRun

    monkeypatch.setattr(run_cli, "get_sessionmaker", lambda: session_factory)
    # Без --dry-run: default true → без записи.
    run_cli.main(
        [
            "--account-id",
            str(account_id),
            "--project-id",
            str(project_id),
            "--platform",
            "telegram",
            "--date",
            _MONDAY,
        ]
    )
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert _TOKEN not in out
    db_session.expire_all()
    assert db_session.query(ScheduleRun).count() == 0  # нет записей в dry-run


def test_run_apply_creates_drafts(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    account_id, project_id = _seed(db_session)
    from app.models.post import Post

    monkeypatch.setattr(run_cli, "get_sessionmaker", lambda: session_factory)
    run_cli.main(
        [
            "--account-id",
            str(account_id),
            "--project-id",
            str(project_id),
            "--platform",
            "telegram",
            "--date",
            _MONDAY,
            "--dry-run",
            "false",
        ]
    )
    out = capsys.readouterr().out
    assert "создано drafts: 1" in out
    assert _TOKEN not in out
    db_session.expire_all()
    assert db_session.query(Post).count() == 1
