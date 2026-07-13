"""Тесты CLI Telegram webhook/polling (v0.5.5). Offline; dry-run; без bot token/сырого chat_id."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import account_repository, user_repository
from app.scripts import (
    telegram_polling_dry,
    telegram_update_simulate,
    telegram_webhook_info,
    telegram_webhook_set,
)
from app.services.notification_telegram_binding_service import (
    NotificationTelegramBindingService,
)


def _seed(db: Session, slug: str = "twcli"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    db.commit()
    return account, owner


def test_scripts_import() -> None:
    assert callable(telegram_update_simulate.main)
    assert callable(telegram_webhook_info.main)
    assert callable(telegram_webhook_set.main)
    assert callable(telegram_polling_dry.main)


def test_webhook_info_cli_dry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["telegram_webhook_info"])
    telegram_webhook_info.main()
    out = capsys.readouterr().out
    assert "getWebhookInfo" in out
    assert "dry-run/sandbox" in out
    assert "live_enabled:      False" in out


def test_webhook_set_cli_dry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["telegram_webhook_set", "--url", "https://app.example.com/notification-telegram/webhook"],
    )
    telegram_webhook_set.main()
    out = capsys.readouterr().out
    assert "setWebhook" in out
    assert "dry_run=True" in out


def test_polling_dry_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["telegram_polling_dry", "--limit", "10"])
    telegram_polling_dry.main()
    out = capsys.readouterr().out
    assert "getUpdates" in out
    assert "limit:        10" in out


def test_simulate_cli_masks_chat_id(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account, owner = _seed(db_session, "twcli-sim")
    res = NotificationTelegramBindingService().create_binding_token(
        db_session, owner.id, account_id=account.id
    )
    monkeypatch.setattr(telegram_update_simulate, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "telegram_update_simulate",
            "--token",
            res["verification_token"],
            "--chat-id",
            "123456789",
        ],
    )
    telegram_update_simulate.main()
    out = capsys.readouterr().out
    # По умолчанию chat_id маской, не сырой.
    assert "***" in out
    assert "123456789" not in out
    assert "verified_binding" in out


def test_simulate_show_unsafe_default_false() -> None:
    args = telegram_update_simulate.build_parser().parse_args(["--token", "T", "--chat-id", "5"])
    assert args.show_unsafe == "false"
