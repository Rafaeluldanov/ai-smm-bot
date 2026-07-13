"""Тесты CLI live-readiness (v0.5.9). Offline; dry-run без записи; без секретов/публикаций."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models.project_live_readiness_profile import ProjectLiveReadinessProfile
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.scripts import (
    live_readiness_check,
    live_readiness_effective_gate,
    live_readiness_enable,
    live_readiness_platform_check,
)


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="П", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def test_scripts_import() -> None:
    assert callable(live_readiness_check.main)
    assert callable(live_readiness_platform_check.main)
    assert callable(live_readiness_enable.main)
    assert callable(live_readiness_effective_gate.main)


def test_check_cli_prints_readiness(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "lrcli-c")
    monkeypatch.setattr(live_readiness_check, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["live_readiness_check", "--project-id", str(project.id), "--dry-run", "true"]
    )
    live_readiness_check.main()
    out = capsys.readouterr().out
    assert "readiness_score:" in out
    assert "status:" in out


def test_platform_check_cli_prints_platform(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "lrcli-p")
    monkeypatch.setattr(live_readiness_platform_check, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "live_readiness_platform_check",
            "--project-id",
            str(project.id),
            "--platform",
            "telegram",
        ],
    )
    live_readiness_platform_check.main()
    out = capsys.readouterr().out
    assert "platform:" in out
    assert "telegram" in out


def test_enable_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "lrcli-e")
    before = db_session.query(ProjectLiveReadinessProfile).count()
    monkeypatch.setattr(live_readiness_enable, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "live_readiness_enable",
            "--project-id",
            str(project.id),
            "--confirmation",
            "ENABLE_LIVE_AUTOPILOT",
            "--dry-run",
            "true",
        ],
    )
    live_readiness_enable.main()
    out = capsys.readouterr().out
    assert "dry_run:         True" in out
    assert db_session.query(ProjectLiveReadinessProfile).count() == before


def test_effective_gate_cli_prints_blockers(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "lrcli-g")
    monkeypatch.setattr(live_readiness_effective_gate, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "live_readiness_effective_gate",
            "--project-id",
            str(project.id),
            "--platform",
            "telegram",
        ],
    )
    live_readiness_effective_gate.main()
    out = capsys.readouterr().out
    assert "can_publish_live:      False" in out
    assert "global_live_flag_disabled" in out


def test_cli_no_secrets_printed(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.services.platform_connection_service import PlatformConnectionService

    _a, project, _o = _seed(db_session, "lrcli-s")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": "123456:SECRETxyz", "external_id": "@x"}
    )
    db_session.commit()
    monkeypatch.setattr(live_readiness_platform_check, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "live_readiness_platform_check",
            "--project-id",
            str(project.id),
            "--platform",
            "telegram",
        ],
    )
    live_readiness_platform_check.main()
    out = capsys.readouterr().out
    assert "123456:SECRETxyz" not in out
