"""Тесты CLI фонового scheduler-worker (tick/loop, dry-run по умолчанию)."""

from sqlalchemy.orm import Session, sessionmaker

from app.repositories import account_repository, project_repository, user_repository
from app.repositories import crm_bot_smm_repository as crm
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.project import ProjectCreate
from app.scripts import scheduler_worker_loop as loop_cli
from app.scripts import scheduler_worker_tick as tick_cli
from app.services import scheduler_worker_service as sws_module

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"


def _seed(db: Session) -> None:
    user = user_repository.create_user(db, email="cli@e.com", password_hash="x")
    account = account_repository.create_account(db, name="A", slug="teeon", owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name="T", slug="teeon"))
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
    from app.services.platform_connection_service import PlatformConnectionService

    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@t"}
    )
    from app.services.billing_service import BillingService

    BillingService().manual_topup(db, account.id, 500, idempotency_key="seed")
    db.commit()


def test_tick_dry_run_default_true(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    _seed(db_session)
    monkeypatch.setattr(tick_cli, "get_sessionmaker", lambda: session_factory)
    from app.models.post import Post

    code = tick_cli.main(["--force", "true", "--now", "2026-07-13T13:00"])
    out = capsys.readouterr().out
    assert code == 0
    assert "dry_run: True" in out
    assert "live-публикация: выключена" in out
    assert _TOKEN not in out
    db_session.expire_all()
    assert db_session.query(Post).count() == 0


def test_tick_create_drafts(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    _seed(db_session)
    monkeypatch.setattr(tick_cli, "get_sessionmaker", lambda: session_factory)
    from app.models.post import Post

    tick_cli.main(["--force", "true", "--dry-run", "false", "--now", "2026-07-13T13:00"])
    out = capsys.readouterr().out
    assert "drafts: 1" in out
    assert _TOKEN not in out
    db_session.expire_all()
    assert db_session.query(Post).count() == 1


def test_loop_once_force_dry_run_prints_summary(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    _seed(db_session)
    monkeypatch.setattr(sws_module, "_default_session_factory", lambda: session_factory())
    loop_cli.main(["--once", "true", "--force", "true", "--dry-run", "true"])
    out = capsys.readouterr().out
    assert "тиков выполнено: 1" in out
    assert "live-публикация: выключена" in out
    assert _TOKEN not in out


def test_loop_disabled_without_force_refuses(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    monkeypatch.setattr(sws_module, "_default_session_factory", lambda: session_factory())
    loop_cli.main(["--once", "true"])  # force default false → отказ (worker disabled)
    out = capsys.readouterr().out
    assert "выключен" in out or "отклонён" in out
