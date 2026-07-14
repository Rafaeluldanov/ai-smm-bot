"""Тесты CLI мониторинга live-автопилота (v0.6.1). Offline; без секретов/публикаций."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import (
    account_repository,
    live_publish_attempt_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.scripts import (
    live_autopilot_monitoring_dashboard as cli_dashboard,
)
from app.scripts import (
    live_autopilot_monitoring_health_check as cli_health,
)
from app.scripts import (
    live_autopilot_monitoring_incidents as cli_incidents,
)
from app.scripts import (
    live_autopilot_monitoring_pause as cli_pause,
)
from app.services.billing_service import BillingService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="П", slug=slug))
    project.account_id = account.id
    db.commit()
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    return account, project, owner


def _fail(db: Session, account, project, n: int) -> None:
    for _ in range(n):
        live_publish_attempt_repository.create_attempt(
            db,
            account_id=account.id,
            project_id=project.id,
            platform_key="telegram",
            status="failed",
            mode="live",
            trigger="auto_schedule",
        )


def test_scripts_import() -> None:
    assert callable(cli_dashboard.main)
    assert callable(cli_health.main)
    assert callable(cli_incidents.main)
    assert callable(cli_pause.main)


def test_dashboard_cli(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "lamcli-d")
    monkeypatch.setattr(cli_dashboard, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["live_autopilot_monitoring_dashboard", "--project-id", str(project.id)]
    )
    cli_dashboard.main()
    out = capsys.readouterr().out
    assert "health:" in out
    assert "can_publish_live:" in out


def test_health_check_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.models.live_autopilot_monitor_snapshot import LiveAutopilotMonitorSnapshot

    acc, project, _o = _seed(db_session, "lamcli-h")
    _fail(db_session, acc, project, 4)
    before = db_session.query(LiveAutopilotMonitorSnapshot).count()
    monkeypatch.setattr(cli_health, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "live_autopilot_monitoring_health_check",
            "--project-id",
            str(project.id),
            "--dry-run",
            "true",
        ],
    )
    cli_health.main()
    out = capsys.readouterr().out
    assert "dry_run:             True" in out
    assert db_session.query(LiveAutopilotMonitorSnapshot).count() == before


def test_incidents_cli(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    acc, project, _o = _seed(db_session, "lamcli-i")
    _fail(db_session, acc, project, 4)
    # Заводим инцидент.
    from app.services.live_autopilot_monitoring_service import LiveAutopilotMonitoringService

    LiveAutopilotMonitoringService().run_health_check(db_session, project.id, dry_run=False)
    monkeypatch.setattr(cli_incidents, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["live_autopilot_monitoring_incidents", "--project-id", str(project.id)]
    )
    cli_incidents.main()
    out = capsys.readouterr().out
    assert "open_incidents:" in out
    assert "repeated_publish_failures" in out


def test_pause_cli_requires_confirmation(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "lamcli-p")
    monkeypatch.setattr(cli_pause, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "live_autopilot_monitoring_pause",
            "--project-id",
            str(project.id),
            "--action",
            "pause",
            "--confirmation",
            "wrong",
        ],
    )
    cli_pause.main()
    out = capsys.readouterr().out
    assert "Отклонено:" in out


def test_pause_cli_no_secrets(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.services.platform_connection_service import PlatformConnectionService

    _a, project, _o = _seed(db_session, "lamcli-s")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": "123456:SECRETxyz", "external_id": "@x"}
    )
    db_session.commit()
    monkeypatch.setattr(cli_dashboard, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["live_autopilot_monitoring_dashboard", "--project-id", str(project.id)]
    )
    cli_dashboard.main()
    out = capsys.readouterr().out
    assert "123456:SECRETxyz" not in out
