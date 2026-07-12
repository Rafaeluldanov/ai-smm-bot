"""Тесты CLI доставки уведомлений/дайджестов (v0.5.1). Offline; dry-run; без секретов."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.scripts import (
    notification_delivery_preview,
    notification_delivery_retry,
    notification_delivery_send,
    notification_digest_generate,
    notification_digest_preview,
    notification_digest_scheduler,
)
from app.services.notification_service import NotificationService

_SECRET = "123456789:cliDELIVERYsecrettoken0123456789"


def _seed(db: Session, slug: str = "clidlv"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    n = NotificationService().create_notification(
        db,
        recipient_user_id=owner.id,
        notification_type="review_assigned",
        title="Задача",
        message="msg",
        account_id=account.id,
        project_id=project.id,
        entity_id=1,
    )
    return account, project, owner, n["id"]


def test_scripts_import() -> None:
    assert callable(notification_delivery_preview.main)
    assert callable(notification_delivery_send.main)
    assert callable(notification_delivery_retry.main)
    assert callable(notification_digest_preview.main)
    assert callable(notification_digest_generate.main)
    assert callable(notification_digest_scheduler.main)


def test_send_parser_dry_run_default_true() -> None:
    args = notification_delivery_send.build_parser().parse_args(["--notification-id", "1"])
    assert args.dry_run == "true"


def test_preview_cli_prints_masked(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, _p, _o, nid = _seed(db_session)
    monkeypatch.setattr(notification_delivery_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["notification_delivery_preview", "--notification-id", str(nid), "--channels", "email"],
    )
    notification_delivery_preview.main()
    out = capsys.readouterr().out
    assert "@" in out and "***" in out  # masked destination


def test_send_cli_dry_run_no_external(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, _p, _o, nid = _seed(db_session)
    monkeypatch.setattr(notification_delivery_send, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["notification_delivery_send", "--notification-id", str(nid), "--channels", "email"],
    )
    notification_delivery_send.main()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "skipped" in out


def test_retry_cli_dry_run(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(db_session)
    monkeypatch.setattr(notification_delivery_retry, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["notification_delivery_retry"])
    notification_delivery_retry.main()
    assert "DRY-RUN" in capsys.readouterr().out


def test_digest_preview_cli(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, _p, owner, _nid = _seed(db_session)
    monkeypatch.setattr(notification_digest_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["notification_digest_preview", "--user-id", str(owner.id), "--frequency", "daily"],
    )
    notification_digest_preview.main()
    assert "Дайджест" in capsys.readouterr().out


def test_digest_generate_cli_dry_run(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, _p, owner, _nid = _seed(db_session)
    monkeypatch.setattr(notification_digest_generate, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["notification_digest_generate", "--user-id", str(owner.id)])
    notification_digest_generate.main()
    assert "DRY-RUN" in capsys.readouterr().out


def test_scheduler_cli_dry_run_no_external(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(db_session)
    monkeypatch.setattr(notification_digest_scheduler, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["notification_digest_scheduler", "--frequency", "daily"])
    notification_digest_scheduler.main()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out


def test_cli_no_secrets(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account, project, owner, _nid = _seed(db_session)
    n = NotificationService().create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="system_notice",
        title=f"secret {_SECRET}",
        message="disk:/private/x.jpg",
        account_id=account.id,
        project_id=project.id,
        entity_id=2,
    )
    monkeypatch.setattr(notification_delivery_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["notification_delivery_preview", "--notification-id", str(n["id"])]
    )
    notification_delivery_preview.main()
    out = capsys.readouterr().out
    assert _SECRET not in out
