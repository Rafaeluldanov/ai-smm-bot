"""Тесты CLI Telegram live rollout (v0.6.0). Offline; dry-run без отправки; без секретов."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models.live_publish_attempt import LivePublishAttempt
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.scripts import (
    telegram_live_rollout_dashboard,
    telegram_live_rollout_preview,
    telegram_live_rollout_publish_once,
    telegram_live_rollout_run_dry,
)
from app.services.platform_connection_service import PlatformConnectionService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="П", slug=slug))
    project.account_id = account.id
    db.commit()
    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": "123456:SECRETxyz", "external_id": "@x"}
    )
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project.id,
            title="T",
            status="approved",
            telegram_text="Hi #x",
            hashtags=["x"],
        ),
    )
    db.commit()
    return account, project, owner, post


def test_scripts_import() -> None:
    assert callable(telegram_live_rollout_dashboard.main)
    assert callable(telegram_live_rollout_preview.main)
    assert callable(telegram_live_rollout_run_dry.main)
    assert callable(telegram_live_rollout_publish_once.main)


def test_dashboard_cli_prints_status(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o, _p = _seed(db_session, "tgcli-d")
    monkeypatch.setattr(
        telegram_live_rollout_dashboard, "get_sessionmaker", lambda: session_factory
    )
    monkeypatch.setattr(
        "sys.argv", ["telegram_live_rollout_dashboard", "--project-id", str(project.id)]
    )
    telegram_live_rollout_dashboard.main()
    out = capsys.readouterr().out
    assert "status:" in out
    assert "can_send_real:" in out
    assert "123456:SECRETxyz" not in out


def test_preview_cli_works(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o, post = _seed(db_session, "tgcli-p")
    monkeypatch.setattr(telegram_live_rollout_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "telegram_live_rollout_preview",
            "--project-id",
            str(project.id),
            "--post-id",
            str(post.id),
        ],
    )
    telegram_live_rollout_preview.main()
    out = capsys.readouterr().out
    assert "can_send_real:" in out
    assert "live_calls:      False" in out


def test_run_dry_cli_no_send(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o, post = _seed(db_session, "tgcli-r")
    monkeypatch.setattr(telegram_live_rollout_run_dry, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "telegram_live_rollout_run_dry",
            "--project-id",
            str(project.id),
            "--post-id",
            str(post.id),
        ],
    )
    telegram_live_rollout_run_dry.main()
    out = capsys.readouterr().out
    assert "live_calls:      False" in out
    assert "units_charged:   0" in out


def test_publish_once_cli_dry_run_no_send(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o, post = _seed(db_session, "tgcli-pub")
    before = db_session.query(LivePublishAttempt).filter_by(status="published").count()
    monkeypatch.setattr(
        telegram_live_rollout_publish_once, "get_sessionmaker", lambda: session_factory
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "telegram_live_rollout_publish_once",
            "--project-id",
            str(project.id),
            "--post-id",
            str(post.id),
            "--confirmation",
            "ENABLE_TELEGRAM_LIVE",
            "--dry-run",
            "true",
        ],
    )
    telegram_live_rollout_publish_once.main()
    out = capsys.readouterr().out
    assert "dry_run:         True" in out
    assert "live_calls:      False" in out
    # dry-run никогда не публикует
    assert db_session.query(LivePublishAttempt).filter_by(status="published").count() == before
