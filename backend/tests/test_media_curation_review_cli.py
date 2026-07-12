"""Тесты CLI collaborative review курирования (v0.4.9). Offline; dry-run; без секретов."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import (
    account_repository,
    media_curation_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import media_asset_repository as media_repo
from app.repositories import media_curation_review_repository as review_repo
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.scripts import (
    media_curation_review_apply,
    media_curation_review_approve,
    media_curation_review_comment,
    media_curation_review_dashboard,
)
from app.services.media_curation_service import MediaCurationService

_SECRET_TOKEN = "555000111:cliREVIEWsecrettoken0123456789"


def _seed(db: Session, slug: str = "clirev"):  # noqa: ANN202
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
    media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project.id,
            file_name="hoodie_dtf.jpg",
            yandex_disk_path=f"disk:/{slug}.jpg",
            source_type="internal",
            license_type=None,
            status="approved",
            tags={},
        ),
    )
    db.commit()
    MediaCurationService().generate_curation_tasks(db, project.id, "telegram", dry_run=False)
    task = next(
        t
        for t in media_curation_repository.list_tasks_for_project(db, project.id)
        if t.task_type in ("retag_suggestion", "missing_tags")
    )
    return account, project, task


def test_scripts_import() -> None:
    assert callable(media_curation_review_dashboard.main)
    assert callable(media_curation_review_comment.main)
    assert callable(media_curation_review_approve.main)
    assert callable(media_curation_review_apply.main)


def test_apply_parser_dry_run_default_true() -> None:
    args = media_curation_review_apply.build_parser().parse_args(["--task-id", "1"])
    assert args.dry_run == "true"
    assert media_curation_review_apply._is_true(args.dry_run) is True


def test_dashboard_cli_prints_counts(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project, _task = _seed(db_session)
    monkeypatch.setattr(
        media_curation_review_dashboard, "get_sessionmaker", lambda: session_factory
    )
    monkeypatch.setattr(
        "sys.argv", ["media_curation_review_dashboard", "--project-id", str(project.id)]
    )
    media_curation_review_dashboard.main()
    out = capsys.readouterr().out
    assert "Ревью медиатеки" in out
    assert "proposed" in out


def test_comment_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, _project, task = _seed(db_session)
    monkeypatch.setattr(media_curation_review_comment, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["media_curation_review_comment", "--task-id", str(task.id), "--comment", "тест"],
    )
    media_curation_review_comment.main()
    assert "DRY-RUN" in capsys.readouterr().out
    assert review_repo.count_comments_for_task(db_session, task.id) == 0


def test_comment_cli_writes_when_not_dry(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, _project, task = _seed(db_session)
    monkeypatch.setattr(media_curation_review_comment, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "media_curation_review_comment",
            "--task-id",
            str(task.id),
            "--comment",
            "оставить главное фото",
            "--dry-run",
            "false",
        ],
    )
    media_curation_review_comment.main()
    assert review_repo.count_comments_for_task(db_session, task.id) >= 1


def test_approve_cli_works(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, _project, task = _seed(db_session)
    monkeypatch.setattr(media_curation_review_approve, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["media_curation_review_approve", "--task-id", str(task.id), "--dry-run", "false"],
    )
    media_curation_review_approve.main()
    db_session.expire_all()  # CLI писал в отдельной сессии того же движка
    assert media_curation_repository.get_task_by_id(db_session, task.id).review_status == "approved"


def test_apply_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, _project, task = _seed(db_session)
    monkeypatch.setattr(media_curation_review_apply, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "media_curation_review_apply",
            "--task-id",
            str(task.id),
            "--action",
            "approve_tags",
        ],
    )
    media_curation_review_apply.main()
    assert "DRY-RUN" in capsys.readouterr().out
    # dry-run не меняет статус согласования.
    assert media_curation_repository.get_task_by_id(db_session, task.id).review_status == "proposed"


def test_cli_prints_no_secrets(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, task_project, task = _seed(db_session)
    monkeypatch.setattr(media_curation_review_comment, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "media_curation_review_comment",
            "--task-id",
            str(task.id),
            "--comment",
            f"secret {_SECRET_TOKEN} disk:/private/x.jpg",
        ],
    )
    media_curation_review_comment.main()
    out = capsys.readouterr().out
    assert _SECRET_TOKEN not in out
    assert "disk:/private" not in out
