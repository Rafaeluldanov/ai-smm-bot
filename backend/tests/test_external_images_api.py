"""Тесты REST API внешних изображений."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import create_topic
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _topic(db: Session, project_id: int) -> int:
    return create_topic(
        db,
        TopicCreate(project_id=project_id, title="Шелкография на футболках", cluster="шелкография"),
    ).id


def _post(db: Session, project_id: int, topic_id: int) -> int:
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id, topic_id=topic_id, title="Шелкография", status="needs_media"
        ),
    ).id


def _search(client: TestClient, db_session: Session) -> list[dict]:
    _project(db_session)
    response = client.post(
        "/external-images/search", json={"project_slug": "teeon", "query": "шелкография"}
    )
    assert response.status_code == 200
    return response.json()["candidates"]


def test_list_empty(client: TestClient) -> None:
    response = client.get("/external-images")
    assert response.status_code == 200
    assert response.json() == []


def test_search(client: TestClient, db_session: Session) -> None:
    candidates = _search(client, db_session)
    assert len(candidates) == 2


def test_search_post_route_ordering(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _post(db_session, project_id, topic_id)
    # /search/post/{id} не должен перехватываться /{candidate_id}.
    response = client.post(f"/external-images/search/post/{post_id}")
    assert response.status_code == 200
    assert response.json()["candidates"]


def test_search_topic(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id)
    response = client.post(f"/external-images/search/topic/{topic_id}")
    assert response.status_code == 200


def test_get_and_safety(client: TestClient, db_session: Session) -> None:
    candidates = _search(client, db_session)
    candidate_id = candidates[0]["id"]

    detail = client.get(f"/external-images/{candidate_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == candidate_id

    safety = client.get(f"/external-images/{candidate_id}/safety")
    assert safety.status_code == 200
    assert safety.json()["can_claim_as_own_case"] is False


def test_review_and_unknown_422(client: TestClient, db_session: Session) -> None:
    candidates = _search(client, db_session)
    candidate_id = candidates[0]["id"]

    ok = client.patch(f"/external-images/{candidate_id}/review", json={"review_status": "approved"})
    assert ok.status_code == 200
    assert ok.json()["review_status"] == "approved"

    bad = client.patch(f"/external-images/{candidate_id}/review", json={"review_status": "bogus"})
    assert bad.status_code == 422


def test_convert_and_rejected_409(client: TestClient, db_session: Session) -> None:
    candidates = _search(client, db_session)
    approved = next(c for c in candidates if c["review_status"] == "approved")
    convert = client.post(f"/external-images/{approved['id']}/convert-to-media", json={})
    assert convert.status_code == 200
    assert convert.json()["media_asset_id"]

    other = next(c for c in candidates if c["id"] != approved["id"])
    client.patch(f"/external-images/{other['id']}/review", json={"review_status": "rejected"})
    blocked = client.post(f"/external-images/{other['id']}/convert-to-media", json={})
    assert blocked.status_code == 409


def test_missing_404(client: TestClient) -> None:
    assert client.get("/external-images/99999").status_code == 404


def test_old_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/posts").status_code == 200
    assert client.get("/analytics/snapshots").status_code == 200
