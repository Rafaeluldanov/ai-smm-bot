"""Тесты REST API медиа-активов."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_yandex_disk_client
from app.integrations.yandex_disk.client import YandexDiskClient, YandexDiskResource
from app.main import app
from app.repositories import media_asset_repository as media_repo
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.project_media_paths import get_default_scan_folders


class FakeClient:
    def __init__(self, files_by_folder: dict[str, list[YandexDiskResource]]) -> None:
        self._files = files_by_folder

    def list_files_recursive(self, path: str, max_depth: int = 3) -> list[YandexDiskResource]:
        return list(self._files.get(path, []))


def test_list_media_assets_empty(client: TestClient) -> None:
    response = client.get("/media-assets")
    assert response.status_code == 200
    assert response.json() == []


def test_list_and_get_media_asset(client: TestClient, db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    asset = media_repo.create_media_asset(
        db_session,
        MediaAssetCreate(project_id=project.id, file_name="a.jpg", yandex_disk_path="disk:/a.jpg"),
    )

    listing = client.get("/media-assets")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = client.get(f"/media-assets/{asset.id}")
    assert detail.status_code == 200
    assert detail.json()["file_name"] == "a.jpg"


def test_get_media_asset_404(client: TestClient) -> None:
    assert client.get("/media-assets/99999").status_code == 404


def test_list_filter_by_status(client: TestClient, db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    media_repo.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project.id, file_name="n.jpg", yandex_disk_path="disk:/n.jpg", status="new"
        ),
    )
    media_repo.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project.id,
            file_name="a.jpg",
            yandex_disk_path="disk:/a.jpg",
            status="approved",
        ),
    )

    response = client.get("/media-assets", params={"status": "approved"})
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_sync_with_mocked_client(client: TestClient, db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    incoming = get_default_scan_folders("teeon")[0]
    name = "Худи с шелкографией.jpg"
    files = {incoming: [YandexDiskResource(name=name, path=f"{incoming}/{name}", type="file")]}
    app.dependency_overrides[get_yandex_disk_client] = lambda: FakeClient(files)
    try:
        response = client.post(f"/media-assets/sync/project/{project.id}")
    finally:
        app.dependency_overrides.pop(get_yandex_disk_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 1
    assert body["project_slug"] == "teeon"
    assert client.get("/media-assets").json()[0]["file_name"] == name


def test_sync_project_not_found(client: TestClient) -> None:
    app.dependency_overrides[get_yandex_disk_client] = lambda: FakeClient({})
    try:
        response = client.post("/media-assets/sync/project/99999")
    finally:
        app.dependency_overrides.pop(get_yandex_disk_client, None)
    assert response.status_code == 404


def test_sync_without_token_returns_503(client: TestClient, db_session: Session) -> None:
    # Реальный клиент без токена -> YandexDiskAuthError -> 503 (детерминированно, без сети).
    create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    app.dependency_overrides[get_yandex_disk_client] = lambda: YandexDiskClient(
        token=None, base_url="https://disk.invalid/v1/disk"
    )
    try:
        response = client.post("/media-assets/sync/slug/teeon")
    finally:
        app.dependency_overrides.pop(get_yandex_disk_client, None)
    assert response.status_code == 503
