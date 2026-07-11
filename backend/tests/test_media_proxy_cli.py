"""Тесты CLI media-proxy: create link (маска по умолчанию), cleanup (dry-run)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.models.public_media_link import PublicMediaLink
from app.repositories import media_asset_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.scripts import create_public_media_link as create_cli
from app.scripts import media_proxy_cleanup as cleanup_cli


def _seed(db: Session) -> tuple[int, int]:
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    asset = media_asset_repository.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project.id, file_name="p.jpg", yandex_disk_path="public://yandex/SMM/p.jpg"
        ),
    )
    db.commit()
    return project.id, asset.id


def test_create_link_masks_by_default(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    pid, aid = _seed(db_session)
    monkeypatch.setattr(create_cli, "get_sessionmaker", lambda: session_factory)
    code = create_cli.main(["--project-id", str(pid), "--media-asset-id", str(aid)])
    out = capsys.readouterr().out
    assert code == 0
    assert "masked URL:" in out
    assert "media/public" in out
    # Реальный URL и raw-токен по умолчанию не печатаются.
    assert "URL:" not in out.replace("masked URL:", "")
    assert "реальный URL скрыт" in out


def test_create_link_show_url(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    pid, aid = _seed(db_session)
    monkeypatch.setattr(create_cli, "get_sessionmaker", lambda: session_factory)
    create_cli.main(["--project-id", str(pid), "--media-asset-id", str(aid), "--show-url", "true"])
    out = capsys.readouterr().out
    assert "URL: http" in out
    assert "/media/public/" in out


def test_cleanup_dry_run_does_not_mutate(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,
    capsys,  # noqa: ANN001
) -> None:
    from app.config import Settings
    from app.services.media_proxy_service import MediaProxyService

    pid, aid = _seed(db_session)
    svc = MediaProxyService(
        settings=Settings(_env_file=None, app_env="local", public_app_url="https://x.ru")
    )
    result = svc.create_public_link(db_session, pid, aid)
    link = db_session.query(PublicMediaLink).one()
    link.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()

    monkeypatch.setattr(cleanup_cli, "get_sessionmaker", lambda: session_factory)
    cleanup_cli.main(["--dry-run", "true"])
    out = capsys.readouterr().out
    assert "dry-run" in out
    # Статус не изменился (dry-run).
    db_session.expire_all()
    assert db_session.get(PublicMediaLink, result.id).status == "active"


def test_cleanup_apply_marks_expired(
    db_session: Session,
    session_factory: sessionmaker,
    monkeypatch,  # noqa: ANN001
) -> None:
    from app.config import Settings
    from app.services.media_proxy_service import MediaProxyService

    pid, aid = _seed(db_session)
    svc = MediaProxyService(
        settings=Settings(_env_file=None, app_env="local", public_app_url="https://x.ru")
    )
    result = svc.create_public_link(db_session, pid, aid)
    link = db_session.query(PublicMediaLink).one()
    link.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()

    monkeypatch.setattr(cleanup_cli, "get_sessionmaker", lambda: session_factory)
    cleanup_cli.main(["--dry-run", "false"])
    db_session.expire_all()
    assert db_session.get(PublicMediaLink, result.id).status == "expired"
