"""Тесты CLI email-шаблонов (v0.5.3). Offline; dry-run; получатель маской; сырой токен скрыт."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.scripts import (
    email_notification_preview,
    email_template_preview,
    email_test_send,
)
from app.services.notification_service import NotificationService


def _seed(db: Session, slug: str = "ecli"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
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
    assert callable(email_template_preview.main)
    assert callable(email_notification_preview.main)
    assert callable(email_test_send.main)


def test_template_preview_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["email_template_preview", "--template-type", "review_assigned"]
    )
    email_template_preview.main()
    out = capsys.readouterr().out
    assert "subject:" in out
    assert "Реальной email-отправки нет" in out


def test_template_preview_list_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["email_template_preview", "--list"])
    email_template_preview.main()
    out = capsys.readouterr().out
    assert "review_assigned" in out


def test_notification_preview_cli_masks_url(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, _p, _o, nid = _seed(db_session, "ecli-np")
    monkeypatch.setattr(email_notification_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["email_notification_preview", "--notification-id", str(nid)])
    email_notification_preview.main()
    out = capsys.readouterr().out
    # По умолчанию unsubscribe маскируется: есть «***», нет полного token=... без маски.
    assert "***" in out
    assert "masked" in out


def test_test_send_cli_blocked_and_masked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["email_test_send", "--to", "secretuser@example.ru", "--template-type", "system_notice"],
    )
    email_test_send.main()
    out = capsys.readouterr().out
    assert "s***@example.ru" in out
    assert "secretuser" not in out
    assert "БЛОКИРОВАНО" in out
    assert "Реальной email-отправки нет" in out


def test_notification_preview_requires_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["email_notification_preview"])
    with pytest.raises(SystemExit):
        email_notification_preview.main()
