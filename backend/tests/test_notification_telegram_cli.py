"""Тесты CLI Telegram-уведомлений (v0.5.4). Offline; dry-run; chat_id маской; без bot token."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.scripts import (
    telegram_binding_create,
    telegram_binding_verify,
    telegram_notification_preview,
    telegram_test_send,
)
from app.services.notification_service import NotificationService


def _seed(db: Session, slug: str = "tcli"):  # noqa: ANN202
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
    assert callable(telegram_binding_create.main)
    assert callable(telegram_binding_verify.main)
    assert callable(telegram_notification_preview.main)
    assert callable(telegram_test_send.main)


def test_binding_create_prints_token_once(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, _p, owner, _nid = _seed(db_session, "tcli-c")
    monkeypatch.setattr(telegram_binding_create, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["telegram_binding_create", "--user-id", str(owner.id)])
    telegram_binding_create.main()
    out = capsys.readouterr().out
    assert "/start" in out
    assert "token prefix:" in out


def test_binding_verify_and_preview_and_test(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account, _p, owner, nid = _seed(db_session, "tcli-v")
    # create token programmatically to feed verify CLI
    from app.services.notification_telegram_binding_service import (
        NotificationTelegramBindingService,
    )

    res = NotificationTelegramBindingService().create_binding_token(
        db_session, owner.id, account_id=account.id
    )
    monkeypatch.setattr(telegram_binding_verify, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "telegram_binding_verify",
            "--token",
            res["verification_token"],
            "--chat-id",
            "123456789",
        ],
    )
    telegram_binding_verify.main()
    out = capsys.readouterr().out
    # chat_id по умолчанию маской, не сырой.
    assert "***" in out
    assert "123456789" not in out

    # preview
    monkeypatch.setattr(telegram_notification_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["telegram_notification_preview", "--notification-id", str(nid)]
    )
    telegram_notification_preview.main()
    prev = capsys.readouterr().out
    assert "subject:" in prev
    assert "Реальной Telegram-отправки нет" in prev

    # test-send dry (blocked by default)
    monkeypatch.setattr(telegram_test_send, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["telegram_test_send", "--user-id", str(owner.id)])
    telegram_test_send.main()
    ts = capsys.readouterr().out
    assert "БЛОКИРОВАНО" in ts
    assert "Реальной Telegram-отправки нет" in ts


def test_preview_list_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["telegram_notification_preview", "--list"])
    telegram_notification_preview.main()
    out = capsys.readouterr().out
    assert "review_assigned" in out


def test_verify_show_unsafe_default_false() -> None:
    args = telegram_binding_verify.build_parser().parse_args(["--token", "T", "--chat-id", "5"])
    assert args.show_unsafe == "false"
