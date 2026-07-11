"""Тесты media-proxy сервиса (offline): токен-хеш, срок, отзыв, тип/размер, HEIC."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.public_media_link import PublicMediaLink
from app.repositories import media_asset_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_proxy_service import (
    MediaProxyError,
    MediaProxyNotAvailableError,
    MediaProxyService,
)

_HTTPS = "https://app.teeon.ru"


class FakeDownloader:
    def __init__(self, data: bytes = b"JPEGDATA" * 10) -> None:
        self.data = data

    def download_public_media(self, disk_path: str, file_name: str):  # noqa: ANN201
        return SimpleNamespace(bytes=self.data, content_type="image/jpeg", file_name=file_name)


class FakeProcessor:
    def enhance_image_bytes(self, image_bytes, profile, operations=None):  # noqa: ANN001, ANN201
        return SimpleNamespace(output_bytes=b"CONVERTED_JPEG_BYTES")


def _settings(**extra) -> Settings:  # noqa: ANN003
    return Settings(_env_file=None, app_env="local", public_app_url=_HTTPS, **extra)


def _svc(settings=None, downloader=None, processor=None) -> MediaProxyService:  # noqa: ANN001
    return MediaProxyService(
        settings=settings or _settings(),
        downloader=downloader or FakeDownloader(),
        image_processor=processor or FakeProcessor(),
    )


def _project_asset(db: Session, file_name: str = "photo.jpg"):  # noqa: ANN202
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    asset = media_asset_repository.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project.id,
            file_name=file_name,
            yandex_disk_path=f"public://yandex/SMM/{file_name}",
        ),
    )
    return project, asset


def test_create_stores_token_hash_not_raw(db_session: Session) -> None:
    project, asset = _project_asset(db_session)
    result = _svc().create_public_link(db_session, project.id, asset.id)
    token = result.url.split("/media/public/")[1]
    link = db_session.query(PublicMediaLink).one()
    assert link.token_hash != token
    assert token not in str(link.__dict__)  # raw токен не в строке
    assert link.token_prefix and link.token_prefix in token


def test_public_url_uses_base_url(db_session: Session) -> None:
    project, asset = _project_asset(db_session)
    result = _svc().create_public_link(db_session, project.id, asset.id)
    assert result.url.startswith(f"{_HTTPS}/media/public/")
    assert "media/public" in result.url_masked
    assert result.url not in result.url_masked  # маска не равна полному URL


def test_resolve_returns_bytes(db_session: Session) -> None:
    project, asset = _project_asset(db_session)
    svc = _svc(downloader=FakeDownloader(b"HELLO_JPEG"))
    result = svc.create_public_link(db_session, project.id, asset.id)
    token = result.url.split("/media/public/")[1]
    resolved = svc.resolve_token(db_session, token)
    assert resolved.content == b"HELLO_JPEG"
    assert resolved.content_type == "image/jpeg"
    assert db_session.query(PublicMediaLink).one().hit_count == 1


def test_expired_link_rejected(db_session: Session) -> None:
    project, asset = _project_asset(db_session)
    svc = _svc()
    result = svc.create_public_link(db_session, project.id, asset.id)
    token = result.url.split("/media/public/")[1]
    link = db_session.query(PublicMediaLink).one()
    link.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    with pytest.raises(MediaProxyNotAvailableError):
        svc.resolve_token(db_session, token)
    assert db_session.query(PublicMediaLink).one().status == "expired"


def test_revoked_link_rejected(db_session: Session) -> None:
    project, asset = _project_asset(db_session)
    svc = _svc()
    result = svc.create_public_link(db_session, project.id, asset.id)
    token = result.url.split("/media/public/")[1]
    assert svc.revoke_link(db_session, project.id, result.id) is True
    with pytest.raises(MediaProxyNotAvailableError):
        svc.resolve_token(db_session, token)


def test_wrong_project_media_rejected(db_session: Session) -> None:
    project, asset = _project_asset(db_session)
    other = create_project(db_session, ProjectCreate(name="Other", slug="other"))
    with pytest.raises(MediaProxyError):
        _svc().create_public_link(db_session, other.id, asset.id)


def test_allowed_content_type_accepted(db_session: Session) -> None:
    project, asset = _project_asset(db_session, "img.png")
    svc = _svc(downloader=FakeDownloader(b"PNGDATA"))
    result = svc.create_public_link(db_session, project.id, asset.id)
    token = result.url.split("/media/public/")[1]
    assert svc.resolve_token(db_session, token).content_type == "image/png"


def test_disallowed_content_type_rejected(db_session: Session) -> None:
    project, asset = _project_asset(db_session, "anim.gif")  # gif не в allowlist
    svc = _svc(downloader=FakeDownloader(b"GIFDATA"))
    result = svc.create_public_link(db_session, project.id, asset.id)
    token = result.url.split("/media/public/")[1]
    with pytest.raises(MediaProxyNotAvailableError):
        svc.resolve_token(db_session, token)


def test_max_bytes_enforced(db_session: Session) -> None:
    project, asset = _project_asset(db_session)
    svc = _svc(settings=_settings(media_proxy_max_bytes=8), downloader=FakeDownloader(b"X" * 100))
    result = svc.create_public_link(db_session, project.id, asset.id)
    token = result.url.split("/media/public/")[1]
    with pytest.raises(MediaProxyNotAvailableError):
        svc.resolve_token(db_session, token)


def test_heic_converted_to_jpeg(db_session: Session) -> None:
    project, asset = _project_asset(db_session, "photo.heic")
    svc = _svc(downloader=FakeDownloader(b"HEICBYTES"), processor=FakeProcessor())
    result = svc.create_public_link(db_session, project.id, asset.id)
    # content_type на ссылке уже jpeg (HEIC → jpg).
    assert result.content_type == "image/jpeg"
    token = result.url.split("/media/public/")[1]
    resolved = svc.resolve_token(db_session, token)
    assert resolved.content == b"CONVERTED_JPEG_BYTES"
    assert resolved.content_type == "image/jpeg"
    assert resolved.file_name.endswith(".jpg")


def test_no_raw_token_in_masked_or_list(db_session: Session) -> None:
    project, asset = _project_asset(db_session)
    svc = _svc()
    result = svc.create_public_link(db_session, project.id, asset.id)
    token = result.url.split("/media/public/")[1]
    listed = svc.list_project_links(db_session, project.id)
    assert token not in str(listed)
    assert token not in result.url_masked
