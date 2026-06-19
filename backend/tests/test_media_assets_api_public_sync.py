"""Тесты REST API публичной синхронизации медиа (fake-сервис, без сети)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_public_media_sync_service
from app.integrations.yandex_disk.client import YandexDiskPublicResource
from app.main import app
from app.repositories.project_repository import create_project
from app.schemas.project import ProjectCreate
from app.services.media_tagging_service import MediaTaggingService
from app.services.public_yandex_disk_media_sync_service import PublicYandexDiskMediaSyncService


def _file(name: str, path: str, media_type: str = "image") -> YandexDiskPublicResource:
    return YandexDiskPublicResource(name=name, path=path, type="file", media_type=media_type)


def _dir(name: str, path: str) -> YandexDiskPublicResource:
    return YandexDiskPublicResource(name=name, path=path, type="dir")


_TREE = {
    "/SMM": [_dir("Тион", "/SMM/Тион"), _dir("Фабрика сувениров", "/SMM/Фабрика сувениров")],
    "/SMM/Тион": [
        _file("a.jpg", "/SMM/Тион/a.jpg"),
        _file("b.mp4", "/SMM/Тион/b.mp4", "video"),
    ],
    "/SMM/Фабрика сувениров": [_file("c.jpg", "/SMM/Фабрика сувениров/c.jpg")],
}


class _FakePublicClient:
    def list_public_resources(self, public_key, path=None, limit=100, offset=0):
        return list(_TREE.get(path or "/", []))

    def list_public_files_recursive(self, public_key, path=None, max_depth=5):
        files: list[YandexDiskPublicResource] = []

        def walk(current: str) -> None:
            for resource in _TREE.get(current, []):
                if resource.is_file:
                    files.append(resource)
                elif resource.is_dir:
                    walk(resource.path)

        walk(path or "/")
        return files

    def get_public_download_url(self, public_key, path=None):
        return "https://dl/x"


def _fake_service() -> PublicYandexDiskMediaSyncService:
    return PublicYandexDiskMediaSyncService(
        client=_FakePublicClient(),
        tagging_service=MediaTaggingService(),
        public_key="https://disk.yandex.ru/d/X",
        root_folder="SMM",
    )


def _unconfigured_service() -> PublicYandexDiskMediaSyncService:
    return PublicYandexDiskMediaSyncService(
        client=_FakePublicClient(),
        tagging_service=MediaTaggingService(),
        public_key=None,
        root_folder="SMM",
    )


def test_public_sync_works(client: TestClient, db_session: Session) -> None:
    create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    app.dependency_overrides[get_public_media_sync_service] = _fake_service
    response = client.post("/media-assets/sync/public/slug/teeon")
    assert response.status_code == 200
    assert response.json()["created"] == 2  # только Тион


def test_public_sync_by_project(client: TestClient, db_session: Session) -> None:
    project_id = create_project(db_session, ProjectCreate(name="TEEON", slug="teeon")).id
    app.dependency_overrides[get_public_media_sync_service] = _fake_service
    response = client.post(f"/media-assets/sync/public/project/{project_id}")
    assert response.status_code == 200


def test_public_sync_missing_project_404(client: TestClient) -> None:
    app.dependency_overrides[get_public_media_sync_service] = _fake_service
    assert client.post("/media-assets/sync/public/slug/nonexistent").status_code == 404


def test_public_sync_not_configured_503(client: TestClient, db_session: Session) -> None:
    create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    app.dependency_overrides[get_public_media_sync_service] = _unconfigured_service
    assert client.post("/media-assets/sync/public/slug/teeon").status_code == 503


def test_old_sync_endpoints_still_exist(client: TestClient) -> None:
    # Приватный sync без проекта по-прежнему отвечает (404 — проекта нет).
    assert client.post("/media-assets/sync/slug/nonexistent").status_code in {404, 503}
