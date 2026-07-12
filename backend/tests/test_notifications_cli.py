"""Тесты CLI уведомлений (v0.5.0). Offline; dry-run; без секретов/внешней доставки."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import (
    account_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.scripts import (
    notifications_inbox,
    notifications_overdue_scan,
    notifications_workload,
)
from app.services.notification_service import NotificationService

_SECRET_TOKEN = "555000111:cliNOTIFsecrettoken0123456789"


def _seed(db: Session, slug: str = "clinotif"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def test_scripts_import() -> None:
    assert callable(notifications_inbox.main)
    assert callable(notifications_overdue_scan.main)
    assert callable(notifications_workload.main)


def test_overdue_parser_dry_run_default_true() -> None:
    args = notifications_overdue_scan.build_parser().parse_args(["--project-id", "1"])
    assert args.dry_run == "true"
    assert notifications_overdue_scan._is_true(args.dry_run) is True


def test_inbox_cli_prints(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account, project, owner = _seed(db_session)
    NotificationService().create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="review_assigned",
        title="Назначена задача",
        message="проверьте",
        account_id=account.id,
        project_id=project.id,
    )
    monkeypatch.setattr(notifications_inbox, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["notifications_inbox", "--user-id", str(owner.id)])
    notifications_inbox.main()
    out = capsys.readouterr().out
    assert "Уведомления пользователя" in out
    assert "review_assigned" in out


def test_overdue_scan_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _account, project, _owner = _seed(db_session)
    monkeypatch.setattr(notifications_overdue_scan, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["notifications_overdue_scan", "--project-id", str(project.id)])
    notifications_overdue_scan.main()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out


def test_workload_cli_prints(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _account, project, _owner = _seed(db_session)
    monkeypatch.setattr(notifications_workload, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["notifications_workload", "--project-id", str(project.id)])
    notifications_workload.main()
    out = capsys.readouterr().out
    assert "Нагрузка ревьюеров" in out


def test_inbox_cli_no_secrets(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account, project, owner = _seed(db_session)
    NotificationService().create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="system_notice",
        title=f"secret {_SECRET_TOKEN}",
        message="disk:/private/x.jpg",
        account_id=account.id,
        project_id=project.id,
    )
    monkeypatch.setattr(notifications_inbox, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["notifications_inbox", "--user-id", str(owner.id)])
    notifications_inbox.main()
    out = capsys.readouterr().out
    assert _SECRET_TOKEN not in out
