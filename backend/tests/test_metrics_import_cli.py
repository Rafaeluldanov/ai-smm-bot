"""Тесты CLI импорта метрик (v0.4.1: импорт, парсинг, запись в тестовую БД)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import (
    account_repository,
    analytics_repository,
    post_publication_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.schemas.project import ProjectCreate
from app.scripts import (
    manual_metrics,
    metrics_import_preview,
    metrics_import_run,
    rebuild_learning_from_metrics,
)
from app.services.billing_service import BillingService


def test_scripts_import() -> None:
    assert callable(metrics_import_preview.main)
    assert callable(metrics_import_run.main)
    assert callable(manual_metrics.main)
    assert callable(rebuild_learning_from_metrics.main)


def test_preview_parser() -> None:
    args = metrics_import_preview.build_parser().parse_args(
        ["--project-id", "1", "--platform", "telegram", "--source", "demo", "--depth", "standard"]
    )
    assert args.project_id == 1
    assert args.platform == "telegram"
    assert args.source == "demo"


def test_run_parser_dry_run_default_true() -> None:
    args = metrics_import_run.build_parser().parse_args(["--project-id", "1"])
    assert args.dry_run == "true"
    assert metrics_import_run._is_true(args.dry_run) is True


def test_rebuild_parser_dry_run_default_true() -> None:
    args = rebuild_learning_from_metrics.build_parser().parse_args(["--project-id", "1"])
    assert args.dry_run == "true"


def test_manual_parser() -> None:
    args = manual_metrics.build_parser().parse_args(
        ["--publication-id", "1", "--views", "1000", "--likes", "50", "--shares", "4"]
    )
    assert args.publication_id == 1
    assert args.views == 1000
    assert args.shares == 4


def _seed_publication(db: Session):  # noqa: ANN202
    user = user_repository.create_user(db, email="cli@e.com", password_hash="x")
    account = account_repository.create_account(db, name="cli", slug="cli-a", owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name="cli", slug="cli-proj"))
    project.account_id = account.id
    db.commit()
    BillingService().manual_topup(db, account.id, 500, idempotency_key="cli")
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project.id,
            title="Пост",
            status="scheduled",
            vk_text="Заказать мерч #мерч",
            hashtags=["мерч"],
        ),
    )
    post.scheduled_at = datetime(2026, 7, 13, 18, 0, tzinfo=UTC)
    pub = post_publication_repository.create_publication(
        db,
        PostPublicationCreate(
            post_id=post.id,
            project_id=project.id,
            platform="vk",
            target_id="-1",
            status="scheduled",
        ),
    )
    db.commit()
    return project, pub


def test_manual_metrics_cli_saves(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _project, pub = _seed_publication(db_session)
    monkeypatch.setattr(manual_metrics, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "manual_metrics",
            "--publication-id",
            str(pub.id),
            "--views",
            "2000",
            "--reach",
            "1500",
            "--likes",
            "100",
            "--impressions",
            "1800",
            "--clicks",
            "40",
        ],
    )
    manual_metrics.main()
    out = capsys.readouterr().out
    assert "Метрики сохранены" in out
    assert "source=manual" in out
    snaps = analytics_repository.list_snapshots(db_session, post_id=pub.post_id)
    assert any(s.source == "manual" for s in snaps)


def test_run_cli_dry_run_no_write(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project, _pub = _seed_publication(db_session)
    monkeypatch.setattr(metrics_import_run, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["metrics_import_run", "--project-id", str(project.id), "--source", "demo"],
    )
    metrics_import_run.main()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    # dry-run не создаёт снимков.
    assert analytics_repository.list_snapshots_for_project(db_session, project.id) == []


def test_rebuild_cli_dry_run_no_write(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project, _pub = _seed_publication(db_session)
    monkeypatch.setattr(rebuild_learning_from_metrics, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["rebuild_learning_from_metrics", "--project-id", str(project.id)],
    )
    rebuild_learning_from_metrics.main()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "списано units: 0" in out


def test_preview_cli_prints_summary_no_secrets(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.services.platform_connection_service import PlatformConnectionService

    project, _pub = _seed_publication(db_session)
    secret = "vksecrettoken1234567890"
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "vk", {"api_key": secret, "external_id": "-1"}
    )
    db_session.commit()
    monkeypatch.setattr(metrics_import_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["metrics_import_preview", "--project-id", str(project.id), "--source", "demo"],
    )
    metrics_import_preview.main()
    out = capsys.readouterr().out
    assert "Превью импорта метрик" in out
    assert "публикаций найдено" in out
    assert secret not in out
