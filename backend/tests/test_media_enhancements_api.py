"""Тесты REST API улучшения медиа (fake-загрузчик + Pillow, без сети)."""

import tempfile
from collections.abc import Callable
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.api.deps import get_media_enhancement_service
from app.main import app
from app.models.media_asset import MediaAsset
from app.repositories.media_asset_repository import create_media_asset
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.image_enhancement_processor import ImageEnhancementProcessor
from app.services.media_download_service import DownloadedMedia
from app.services.media_enhancement_service import MediaEnhancementService


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1200, 800), (120, 90, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeDownloader:
    def download_media_asset(self, db: Session, media_asset: MediaAsset) -> DownloadedMedia:
        return DownloadedMedia(
            file_name=media_asset.file_name,
            content_type="image/png",
            bytes=_png(),
            source_url="fake://x",
        )


def _service_factory(storage_dir: str) -> Callable[[], MediaEnhancementService]:
    def build() -> MediaEnhancementService:
        return MediaEnhancementService(
            processor=ImageEnhancementProcessor(),
            downloader=_FakeDownloader(),
            storage_dir=storage_dir,
            default_profile="social_safe",
        )

    return build


def _seed(db: Session, file_name: str = "a.jpg") -> tuple[int, int]:
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    media = create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project.id,
            file_name=file_name,
            yandex_disk_path=f"public://yandex/teeon/SMM/Тион/{file_name}",
            status="approved",
        ),
    )
    return project.id, media.id


def test_enhance_list_summary_patch_get(
    client: TestClient, db_session: Session, tmp_path: object
) -> None:
    project_id, media_id = _seed(db_session)
    app.dependency_overrides[get_media_enhancement_service] = _service_factory(str(tmp_path))

    enhance = client.post(
        f"/media-enhancements/media/{media_id}/enhance", json={"profile": "social_safe"}
    )
    assert enhance.status_code == 200
    body = enhance.json()
    assert body["status"] == "created"
    variant_id = body["variant"]["id"]

    listed = client.get("/media-enhancements", params={"media_asset_id": media_id})
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    summary = client.get("/media-enhancements/summary", params={"project_id": project_id})
    assert summary.status_code == 200
    assert summary.json()["total_variants"] == 1

    patched = client.patch(f"/media-enhancements/{variant_id}/status", json={"status": "approved"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "approved"

    fetched = client.get(f"/media-enhancements/{variant_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == variant_id


def test_enhance_conflict_then_force(
    client: TestClient, db_session: Session, tmp_path: object
) -> None:
    _project_id, media_id = _seed(db_session)
    app.dependency_overrides[get_media_enhancement_service] = _service_factory(str(tmp_path))
    first = client.post(f"/media-enhancements/media/{media_id}/enhance", json={})
    assert first.status_code == 200
    conflict = client.post(f"/media-enhancements/media/{media_id}/enhance", json={})
    assert conflict.status_code == 409
    forced = client.post(f"/media-enhancements/media/{media_id}/enhance", json={"force": True})
    assert forced.status_code == 200


def test_enhance_missing_media_404(client: TestClient) -> None:
    app.dependency_overrides[get_media_enhancement_service] = _service_factory(tempfile.mkdtemp())
    assert client.post("/media-enhancements/media/999/enhance", json={}).status_code == 404


def test_get_missing_variant_404(client: TestClient) -> None:
    assert client.get("/media-enhancements/999").status_code == 404


def test_patch_invalid_status_422(
    client: TestClient, db_session: Session, tmp_path: object
) -> None:
    _project_id, media_id = _seed(db_session)
    app.dependency_overrides[get_media_enhancement_service] = _service_factory(str(tmp_path))
    body = client.post(f"/media-enhancements/media/{media_id}/enhance", json={}).json()
    variant_id = body["variant"]["id"]
    bad = client.patch(f"/media-enhancements/{variant_id}/status", json={"status": "nonsense"})
    assert bad.status_code == 422


def test_summary_route_resolves_before_variant_id(client: TestClient) -> None:
    # /summary должен попасть в сводку, а не в /{variant_id}.
    response = client.get("/media-enhancements/summary")
    assert response.status_code == 200
    assert "total_variants" in response.json()


def test_project_batch_api(client: TestClient, db_session: Session, tmp_path: object) -> None:
    _seed(db_session, file_name="a.jpg")
    app.dependency_overrides[get_media_enhancement_service] = _service_factory(str(tmp_path))
    response = client.post(
        "/media-enhancements/project",
        json={"project_slug": "teeon", "status": "approved", "profile": "social_safe"},
    )
    assert response.status_code == 200
    assert response.json()["enhanced"] == 1


def test_project_missing_404(client: TestClient, tmp_path: object) -> None:
    app.dependency_overrides[get_media_enhancement_service] = _service_factory(str(tmp_path))
    response = client.post("/media-enhancements/project", json={"project_slug": "nope"})
    assert response.status_code == 404
