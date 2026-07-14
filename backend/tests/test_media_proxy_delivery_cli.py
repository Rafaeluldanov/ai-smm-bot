"""Тесты CLI media-proxy delivery v0.6.2 (offline): generate, check. Без секретов."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models.media_asset import MediaAsset
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.scripts import media_proxy_check, media_proxy_generate


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="P", slug=slug))
    project.account_id = account.id
    db.commit()
    asset = MediaAsset(
        project_id=project.id,
        file_name="pic.jpg",
        yandex_disk_path=f"public://yandex/{slug}/pic.jpg",
    )
    db.add(asset)
    db.commit()
    return account, project, asset


def test_scripts_import() -> None:
    assert callable(media_proxy_generate.main)
    assert callable(media_proxy_check.main)


def test_generate_cli_masks_url_by_default(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _a, project, asset = _seed(db_session, "mpcli-gen")
    monkeypatch.setattr(media_proxy_generate, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        media_proxy_generate,
        "MediaProxyService",
        lambda: __import__(
            "app.services.media_proxy_service", fromlist=["MediaProxyService"]
        ).MediaProxyService(
            settings=Settings(media_proxy_public_base_url="https://media.example.com")
        ),
    )
    rc = media_proxy_generate.main(
        [
            "--project-id",
            str(project.id),
            "--media-asset-id",
            str(asset.id),
            "--transform",
            "width_1080",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "transform:    width_1080" in out
    assert "masked URL:" in out
    # URL маскирован (…••••), полный токен не печатается; реальный URL скрыт по умолчанию.
    assert "…••••" in out
    assert "реальный URL скрыт" in out


def test_check_cli_shows_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = media_proxy_check.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "enabled:" in out
    assert "allow_original:" in out
    assert "resize_enabled:" in out
