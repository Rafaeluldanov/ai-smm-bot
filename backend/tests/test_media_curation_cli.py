"""Тесты CLI курирования медиатеки (v0.4.8). Offline; dry-run; без секретов/путей/удаления."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import (
    account_repository,
    media_curation_repository,
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
    media_curation_apply,
    media_curation_dashboard,
    media_curation_generate,
    media_curation_preview,
)
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "555000111:cliCURsecrettoken"


def _seed(db: Session, slug: str = "clicur"):  # noqa: ANN202
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
    for i in range(2):
        media_repo.create_media_asset(
            db,
            MediaAssetCreate(
                project_id=project.id,
                file_name=f"hoodie_dtf_{i}.jpg",
                yandex_disk_path=f"disk:/{slug}-{i}.jpg",
                source_type="internal",
                license_type=None,
                status="approved",
                tags={},
            ),
        )
    db.commit()
    return account, project


def test_scripts_import() -> None:
    assert callable(media_curation_preview.main)
    assert callable(media_curation_generate.main)
    assert callable(media_curation_apply.main)
    assert callable(media_curation_dashboard.main)


def test_generate_parser_dry_run_default_true() -> None:
    args = media_curation_generate.build_parser().parse_args(["--project-id", "1"])
    assert args.dry_run == "true"
    assert media_curation_generate._is_true(args.dry_run) is True


def test_preview_cli_prints_tasks(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(media_curation_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["media_curation_preview", "--project-id", str(project.id)])
    media_curation_preview.main()
    out = capsys.readouterr().out
    assert "задач найдено" in out.lower()
    assert media_curation_repository.list_tasks_for_project(db_session, project.id) == []


def test_generate_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(media_curation_generate, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["media_curation_generate", "--project-id", str(project.id)])
    media_curation_generate.main()
    assert "DRY-RUN" in capsys.readouterr().out
    assert media_curation_repository.list_tasks_for_project(db_session, project.id) == []


def test_generate_cli_writes_when_not_dry(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(media_curation_generate, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["media_curation_generate", "--project-id", str(project.id), "--dry-run", "false"],
    )
    media_curation_generate.main()
    assert "задач создано" in capsys.readouterr().out.lower()
    assert len(media_curation_repository.list_tasks_for_project(db_session, project.id)) >= 1


def test_apply_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    from app.services.media_curation_service import MediaCurationService

    MediaCurationService().generate_curation_tasks(
        db_session, project.id, "telegram", dry_run=False
    )
    task = media_curation_repository.list_tasks_for_project(db_session, project.id)[0]
    monkeypatch.setattr(media_curation_apply, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["media_curation_apply", "--task-id", str(task.id), "--action", "approve_tags"],
    )
    media_curation_apply.main()
    assert "DRY-RUN" in capsys.readouterr().out
    # dry-run не меняет статус задачи.
    assert media_curation_repository.get_task_by_id(db_session, task.id).status == "proposed"


def test_dashboard_cli_prints_summary(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(media_curation_dashboard, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["media_curation_dashboard", "--project-id", str(project.id)])
    media_curation_dashboard.main()
    assert "Сводка курирования" in capsys.readouterr().out


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
    monkeypatch.setattr(media_curation_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["media_curation_preview", "--project-id", str(project.id)])
    media_curation_preview.main()
    out = capsys.readouterr().out
    assert _SECRET_TOKEN not in out
    assert "api_key" not in out
    assert "disk:/" not in out
