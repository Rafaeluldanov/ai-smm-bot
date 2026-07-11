"""Тесты media-proxy API: создание, публичная отдача, 404, список, отзыв (offline)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import app
from app.models.public_media_link import PublicMediaLink
from app.repositories import media_asset_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_proxy_service import MediaProxyService, get_media_proxy_service


class FakeDownloader:
    def download_public_media(self, disk_path: str, file_name: str):  # noqa: ANN201
        return SimpleNamespace(
            bytes=b"JPEGBYTES" * 5, content_type="image/jpeg", file_name=file_name
        )


@pytest.fixture()
def proxy_setup(client: TestClient, db_session: Session):  # noqa: ANN201
    project = create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    asset = media_asset_repository.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project.id, file_name="p.jpg", yandex_disk_path="public://yandex/SMM/p.jpg"
        ),
    )
    db_session.commit()
    settings = Settings(_env_file=None, app_env="local", public_app_url="https://app.teeon.ru")
    app.dependency_overrides[get_media_proxy_service] = lambda: MediaProxyService(
        settings=settings, downloader=FakeDownloader()
    )
    try:
        yield client, project, asset
    finally:
        app.dependency_overrides.pop(get_media_proxy_service, None)


def _create(client: TestClient, project_id: int, asset_id: int) -> dict:
    r = client.post(
        f"/media-proxy/projects/{project_id}/media-assets/{asset_id}/public-link",
        json={"purpose": "instagram", "ttl_seconds": 3600},
    )
    assert r.status_code == 200
    return r.json()


def test_create_and_serve(proxy_setup) -> None:  # noqa: ANN001
    client, project, asset = proxy_setup
    data = _create(client, project.id, asset.id)
    assert "media/public" in data["url_masked"]
    token = data["url"].split("/media/public/")[1]
    resp = client.get(f"/media/public/{token}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "max-age" in resp.headers["cache-control"]
    assert resp.content == b"JPEGBYTES" * 5


def test_invalid_token_404(proxy_setup) -> None:  # noqa: ANN001
    client, _project, _asset = proxy_setup
    assert client.get("/media/public/definitely-not-a-real-token").status_code == 404


def test_expired_token_404(proxy_setup, db_session: Session) -> None:  # noqa: ANN001
    client, project, asset = proxy_setup
    token = _create(client, project.id, asset.id)["url"].split("/media/public/")[1]
    link = db_session.query(PublicMediaLink).one()
    link.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    assert client.get(f"/media/public/{token}").status_code == 404


def test_revoked_token_404(proxy_setup) -> None:  # noqa: ANN001
    client, project, asset = proxy_setup
    data = _create(client, project.id, asset.id)
    token = data["url"].split("/media/public/")[1]
    assert client.delete(f"/media-proxy/projects/{project.id}/links/{data['id']}").json()["revoked"]
    assert client.get(f"/media/public/{token}").status_code == 404


def test_list_masked_no_raw_token(proxy_setup) -> None:  # noqa: ANN001
    client, project, asset = proxy_setup
    data = _create(client, project.id, asset.id)
    token = data["url"].split("/media/public/")[1]
    r = client.get(f"/media-proxy/projects/{project.id}/links")
    assert r.status_code == 200 and len(r.json()) == 1
    assert token not in r.text
    assert "token_hash" not in r.text


def test_public_get_needs_no_auth(proxy_setup) -> None:  # noqa: ANN001
    # Клиент анонимный (local) — публичная отдача не требует авторизации.
    client, project, asset = proxy_setup
    token = _create(client, project.id, asset.id)["url"].split("/media/public/")[1]
    assert client.get(f"/media/public/{token}").status_code == 200


def test_status_endpoint(proxy_setup) -> None:  # noqa: ANN001
    client, project, _asset = proxy_setup
    r = client.get(f"/media-proxy/projects/{project.id}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["https_ready"] is True
    assert "default_ttl_seconds" in body
