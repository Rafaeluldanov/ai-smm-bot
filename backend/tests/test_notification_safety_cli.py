"""Тесты CLI safety-слоя уведомлений (v0.5.2). Offline; dry-run; без секретов."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.scripts import (
    notification_opt_out,
    notification_safety_dashboard,
    notification_suppression_clear,
    webhook_subscription_create,
    webhook_subscription_preview,
)
from app.services.webhook_subscription_service import WebhookSubscriptionService

_URL = "https://hooks.example.com/secret/path"
_SECRET = "clisecret0123456789abcdef"


def _seed(db: Session, slug: str = "clisafe"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def test_scripts_import() -> None:
    assert callable(notification_safety_dashboard.main)
    assert callable(notification_opt_out.main)
    assert callable(notification_suppression_clear.main)
    assert callable(webhook_subscription_create.main)
    assert callable(webhook_subscription_preview.main)


def test_opt_out_parser_dry_run_default_true() -> None:
    args = notification_opt_out.build_parser().parse_args(["--user-id", "1"])
    assert args.dry_run == "true"


def test_dashboard_cli(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, _p, owner = _seed(db_session)
    monkeypatch.setattr(notification_safety_dashboard, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["notification_safety_dashboard", "--user-id", str(owner.id)])
    notification_safety_dashboard.main()
    out = capsys.readouterr().out
    assert "Безопасность уведомлений" in out


def test_opt_out_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.repositories import notification_safety_repository as safety_repo

    _a, _p, owner = _seed(db_session)
    monkeypatch.setattr(notification_opt_out, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["notification_opt_out", "--user-id", str(owner.id), "--scope", "global"]
    )
    notification_opt_out.main()
    assert "DRY-RUN" in capsys.readouterr().out
    assert safety_repo.list_opt_outs_for_user(db_session, owner.id) == []


def test_webhook_create_cli_dry_run_masked(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account, _p, _o = _seed(db_session)
    monkeypatch.setattr(webhook_subscription_create, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["webhook_subscription_create", "--account-id", str(account.id), "--url", _URL],
    )
    webhook_subscription_create.main()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert _URL not in out  # только маска
    assert "/***" in out


def test_webhook_preview_cli(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account, project, _o = _seed(db_session)
    view = WebhookSubscriptionService().create_subscription(
        db_session, account.id, "h", _URL, project_id=project.id, signing_secret=_SECRET
    )
    monkeypatch.setattr(webhook_subscription_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["webhook_subscription_preview", "--subscription-id", str(view["id"])]
    )
    webhook_subscription_preview.main()
    out = capsys.readouterr().out
    assert "would_send: False" in out
    assert _URL not in out and _SECRET not in out
