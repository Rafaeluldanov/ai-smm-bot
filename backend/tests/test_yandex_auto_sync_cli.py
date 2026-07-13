"""Тесты CLI авто-синхронизации Яндекс Диска (v0.5.7). Offline; dry-run; без секретов/путей."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models.media_asset import MediaAsset
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.scripts import (
    yandex_sync_preview,
    yandex_sync_profile,
    yandex_sync_run,
    yandex_sync_worker_tick,
)
from app.services.yandex_auto_sync_service import YandexAutoSyncService


def _seed(db: Session, slug: str = "yscli"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="П", slug=slug))
    project.account_id = account.id
    db.commit()
    YandexAutoSyncService().configure_profile(
        db, project.id, {"public_url": "https://disk.yandex.ru/d/SECRET123", "root_folder": "SMM"}
    )
    for i in range(6):
        db.add(
            MediaAsset(project_id=project.id, file_name=f"i{i}.jpg", yandex_disk_path=f"/i{i}.jpg")
        )
    db.commit()
    return account, project, owner


def test_scripts_import() -> None:
    assert callable(yandex_sync_profile.main)
    assert callable(yandex_sync_preview.main)
    assert callable(yandex_sync_run.main)
    assert callable(yandex_sync_worker_tick.main)


def test_profile_cli_prints_summary(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "yscli-p")
    monkeypatch.setattr(yandex_sync_profile, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["yandex_sync_profile", "--project-id", str(project.id)])
    yandex_sync_profile.main()
    out = capsys.readouterr().out
    assert "media_count:" in out
    assert "/d/SECRET123" not in out  # сырой url не печатается


def test_preview_cli_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "yscli-pv")
    before = db_session.query(MediaAsset).count()
    monkeypatch.setattr(yandex_sync_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["yandex_sync_preview", "--project-id", str(project.id)])
    yandex_sync_preview.main()
    out = capsys.readouterr().out
    assert "writes:" in out
    assert db_session.query(MediaAsset).count() == before


def test_run_cli_dry_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, _o = _seed(db_session, "yscli-run")
    before = db_session.query(MediaAsset).count()
    monkeypatch.setattr(yandex_sync_run, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["yandex_sync_run", "--project-id", str(project.id), "--dry-run", "true"]
    )
    yandex_sync_run.main()
    out = capsys.readouterr().out
    assert "status:" in out
    assert "Файлы не удаляются" in out
    assert db_session.query(MediaAsset).count() == before


def test_worker_tick_cli(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(yandex_sync_worker_tick, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["yandex_sync_worker_tick", "--dry-run", "true"])
    yandex_sync_worker_tick.main()
    out = capsys.readouterr().out
    assert "enabled:" in out
    assert "Реальной сети/удаления нет" in out
