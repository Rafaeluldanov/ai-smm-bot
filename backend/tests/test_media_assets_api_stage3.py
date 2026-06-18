"""Тесты новых эндпоинтов media-assets (Этап 3)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import media_asset_repository as media_repo
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _asset(db: Session, project_id: int, file_name: str, status: str = "new") -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=file_name,
            yandex_disk_path=f"disk:/{file_name}",
            status=status,
        ),
    )
    return asset.id


def test_analyze_endpoint_saves_tags(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, "Худи с шелкографией.jpg")

    response = client.post(f"/media-assets/{asset_id}/analyze", params={"save": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["tags"]["products"] == ["худи"]

    # Теги сохранены в БД.
    detail = client.get(f"/media-assets/{asset_id}").json()
    assert detail["tags"]["technologies"] == ["шелкография"]


def test_analyze_endpoint_404(client: TestClient) -> None:
    assert client.post("/media-assets/99999/analyze").status_code == 404


def test_retag_single_endpoint(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, "Кружка с УФ печатью.jpg")

    response = client.post(f"/media-assets/{asset_id}/retag")
    assert response.status_code == 200
    assert "уф-печать" in response.json()["tags"]["technologies"]


def test_retag_project_endpoint(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    _asset(db_session, project_id, "Футболка DTF.png")
    _asset(db_session, project_id, "Свитшот с вышивкой.jpg")

    response = client.post(f"/media-assets/retag/project/{project_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 2
    assert body["updated"] == 2


def test_retag_slug_endpoint(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    _asset(db_session, project_id, "Шоппер с шелкографией.jpg")

    response = client.post("/media-assets/retag/slug/teeon")
    assert response.status_code == 200
    assert response.json()["project_slug"] == "teeon"


def test_retag_project_404(client: TestClient) -> None:
    assert client.post("/media-assets/retag/project/99999").status_code == 404


def test_tags_summary_endpoint(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, "Худи с шелкографией.jpg")
    client.post(f"/media-assets/{asset_id}/retag")

    response = client.get("/media-assets/tags/summary", params={"project_id": project_id})
    assert response.status_code == 200
    body = response.json()
    assert body["total_assets"] == 1
    assert body["products"]["худи"] == 1


def test_shooting_suggestions_endpoint(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    response = client.get("/media-assets/shooting-suggestions", params={"project_id": project_id})
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) > 0
    assert tasks[0]["project_slug"] == "teeon"


def test_shooting_suggestions_404(client: TestClient) -> None:
    response = client.get("/media-assets/shooting-suggestions", params={"project_id": 99999})
    assert response.status_code == 404


def test_status_patch_valid(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, "Худи.jpg", status="new")

    response = client.patch(f"/media-assets/{asset_id}/status", json={"status": "approved"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_status_patch_unknown_status_422(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, "Худи.jpg")
    response = client.patch(f"/media-assets/{asset_id}/status", json={"status": "bogus"})
    assert response.status_code == 422


def test_status_patch_forbidden_transition_409(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, "Сток.jpg", status="needs_license_review")
    response = client.patch(f"/media-assets/{asset_id}/status", json={"status": "used"})
    assert response.status_code == 409


def test_status_patch_404(client: TestClient) -> None:
    response = client.patch("/media-assets/99999/status", json={"status": "approved"})
    assert response.status_code == 404


def test_old_endpoints_still_work(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    _asset(db_session, project_id, "Худи.jpg")
    assert client.get("/media-assets").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/projects").status_code == 200
