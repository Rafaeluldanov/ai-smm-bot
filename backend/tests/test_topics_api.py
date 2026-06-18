"""Тесты REST API тем и контент-плана."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories.project_repository import create_project
from app.schemas.project import ProjectCreate


def _teeon(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def test_list_topics_empty(client: TestClient) -> None:
    response = client.get("/topics")
    assert response.status_code == 200
    assert response.json() == []


def test_select_by_slug_and_route_ordering(client: TestClient, db_session: Session) -> None:
    _teeon(db_session)
    # /topics/select/slug/teeon не должен перехватываться /topics/{topic_id}.
    response = client.post("/topics/select/slug/teeon", json={"posts_per_week": 3, "weeks": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["project_slug"] == "teeon"
    assert body["selected_count"] > 0


def test_select_by_project_and_get(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    select = client.post(
        f"/topics/select/project/{project_id}",
        json={"business_priorities": {"футболки": 100}, "posts_per_week": 3},
    )
    assert select.status_code == 200

    listing = client.get("/topics", params={"project_id": project_id})
    assert listing.status_code == 200
    topics = listing.json()
    assert len(topics) > 0

    topic_id = topics[0]["id"]
    detail = client.get(f"/topics/{topic_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == topic_id


def test_get_topic_404(client: TestClient) -> None:
    assert client.get("/topics/99999").status_code == 404


def test_select_project_404(client: TestClient) -> None:
    assert client.post("/topics/select/project/99999", json={}).status_code == 404


def test_weekly_plan_by_slug(client: TestClient, db_session: Session) -> None:
    _teeon(db_session)
    response = client.post("/topics/weekly-plan/slug/teeon", json={"posts_per_week": 3, "weeks": 1})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["suggested_day"] == "Понедельник"


def test_weekly_plan_by_project(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    response = client.post(f"/topics/weekly-plan/project/{project_id}", json={})
    assert response.status_code == 200
    assert response.json()["project_id"] == project_id


def test_weekly_plan_404(client: TestClient) -> None:
    assert client.post("/topics/weekly-plan/project/99999", json={}).status_code == 404


def test_patch_status_planned(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    client.post(f"/topics/select/project/{project_id}", json={})
    topic_id = client.get("/topics", params={"project_id": project_id}).json()[0]["id"]

    response = client.patch(f"/topics/{topic_id}/status", json={"status": "planned"})
    assert response.status_code == 200
    assert response.json()["status"] == "planned"


def test_patch_status_invalid_422(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    client.post(f"/topics/select/project/{project_id}", json={})
    topic_id = client.get("/topics", params={"project_id": project_id}).json()[0]["id"]

    response = client.patch(f"/topics/{topic_id}/status", json={"status": "bogus"})
    assert response.status_code == 422


def test_old_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/projects").status_code == 200
    assert client.get("/media-assets").status_code == 200
