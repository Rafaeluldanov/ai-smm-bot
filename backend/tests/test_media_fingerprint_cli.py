"""Тесты CLI fingerprint/дублей медиа (v0.4.7). Offline; dry-run; без секретов/путей."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import (
    account_repository,
    media_fingerprint_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.scripts import (
    media_duplicate_dashboard,
    media_duplicate_preview,
    media_fingerprint_calculate,
    media_fingerprint_preview,
)
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "555000111:cliFPsecrettoken"


def _seed(db: Session, slug: str = "clifp"):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    cfg = crm.create_config(db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug))
    crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id,
            config_id=cfg.id,
            title="Мерч",
            cta="Заказать",
            media_tags=["мерч"],
        ),
    )
    for i in range(3):
        media_repo.create_media_asset(
            db,
            MediaAssetCreate(
                project_id=project.id,
                file_name=f"img{i}.jpg",
                yandex_disk_path=f"disk:/{slug}-{i}.jpg",
                source_type="internal",
                license_type=None,
                status="approved",
                tags={"products": ["мерч"]},
            ),
        )
    db.commit()
    return account, project


def test_scripts_import() -> None:
    assert callable(media_fingerprint_preview.main)
    assert callable(media_fingerprint_calculate.main)
    assert callable(media_duplicate_preview.main)
    assert callable(media_duplicate_dashboard.main)


def test_calculate_parser_dry_run_default_true() -> None:
    args = media_fingerprint_calculate.build_parser().parse_args(["--project-id", "1"])
    assert args.dry_run == "true"
    assert media_fingerprint_calculate._is_true(args.dry_run) is True


def test_preview_cli_prints_summary(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(media_fingerprint_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["media_fingerprint_preview", "--project-id", str(project.id)])
    media_fingerprint_preview.main()
    out = capsys.readouterr().out
    assert "просканировано:" in out.lower()
    assert media_fingerprint_repository.list_for_project(db_session, project.id) == []


def test_calculate_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(media_fingerprint_calculate, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["media_fingerprint_calculate", "--project-id", str(project.id)]
    )
    media_fingerprint_calculate.main()
    assert "DRY-RUN" in capsys.readouterr().out
    assert media_fingerprint_repository.list_for_project(db_session, project.id) == []


def test_calculate_cli_writes_when_not_dry(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(media_fingerprint_calculate, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["media_fingerprint_calculate", "--project-id", str(project.id), "--dry-run", "false"],
    )
    media_fingerprint_calculate.main()
    out = capsys.readouterr().out
    assert "создано записей" in out.lower()
    assert len(media_fingerprint_repository.list_for_project(db_session, project.id)) == 3


def test_duplicate_preview_cli_prints_clusters(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(media_duplicate_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["media_duplicate_preview", "--project-id", str(project.id)])
    media_duplicate_preview.main()
    assert "найдено кластеров" in capsys.readouterr().out.lower()


def test_dashboard_cli_prints_summary(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(media_duplicate_dashboard, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["media_duplicate_dashboard", "--project-id", str(project.id)])
    media_duplicate_dashboard.main()
    assert "Сводка дублей медиа" in capsys.readouterr().out


def test_cli_prints_no_secrets_or_paths(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    monkeypatch.setattr(media_fingerprint_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["media_fingerprint_preview", "--project-id", str(project.id)])
    media_fingerprint_preview.main()
    out = capsys.readouterr().out
    assert _SECRET_TOKEN not in out
    assert "api_key" not in out
    assert "disk:/" not in out
