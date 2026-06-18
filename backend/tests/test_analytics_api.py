"""Тесты REST API аналитики."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import post_publication_repository, post_repository
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import create_topic
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _topic(db: Session, project_id: int) -> int:
    return create_topic(
        db, TopicCreate(project_id=project_id, title="Футболки", cluster="футболки")
    ).id


def _post(db: Session, project_id: int, topic_id: int | None = None) -> int:
    return post_repository.create_post(
        db, PostCreate(project_id=project_id, topic_id=topic_id, title="Пост", status="published")
    ).id


def _publication(db: Session, project_id: int, post_id: int) -> int:
    return post_publication_repository.create_publication(
        db,
        PostPublicationCreate(
            post_id=post_id, project_id=project_id, platform="telegram", status="published"
        ),
    ).id


def test_list_snapshots_empty_and_route_ordering(client: TestClient) -> None:
    # /analytics/snapshots не должен перехватываться /snapshots/{snapshot_id}.
    response = client.get("/analytics/snapshots")
    assert response.status_code == 200
    assert response.json() == []


def test_create_and_get_snapshot(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    created = client.post(
        "/analytics/snapshots",
        json={"post_id": post_id, "platform": "telegram", "impressions": 1000, "clicks": 20},
    )
    assert created.status_code == 200
    snapshot_id = created.json()["id"]
    assert created.json()["ctr"] == 0.02

    detail = client.get(f"/analytics/snapshots/{snapshot_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == snapshot_id


def test_create_snapshot_missing_post_404(client: TestClient) -> None:
    response = client.post("/analytics/snapshots", json={"post_id": 99999, "platform": "telegram"})
    assert response.status_code == 404


def test_ingest_and_fetch_publication(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    publication_id = _publication(db_session, project_id, post_id)

    ingested = client.post(
        f"/analytics/ingest/publication/{publication_id}",
        json={"metrics": {"impressions": 1000, "clicks": 30}, "source": "manual"},
    )
    assert ingested.status_code == 200
    assert ingested.json()["snapshot"]["post_publication_id"] == publication_id

    fetched = client.post(f"/analytics/fetch/publication/{publication_id}", json={})
    assert fetched.status_code == 200
    assert fetched.json()["snapshot"]["source"] == "fake_provider"


def test_fetch_missing_publication_404(client: TestClient) -> None:
    assert client.post("/analytics/fetch/publication/99999", json={}).status_code == 404


def test_reports(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _post(db_session, project_id, topic_id)
    client.post(
        "/analytics/snapshots",
        json={
            "post_id": post_id,
            "platform": "telegram",
            "impressions": 5000,
            "reach": 5000,
            "likes": 1000,
            "clicks": 600,
        },
    )

    assert client.get(f"/analytics/posts/{post_id}/performance").status_code == 200
    assert client.get(f"/analytics/projects/{project_id}/topics").status_code == 200
    assert client.get(f"/analytics/projects/{project_id}/clusters").status_code == 200
    assert client.get(f"/analytics/projects/{project_id}/summary").status_code == 200
    assert client.get(f"/analytics/projects/{project_id}/feedback").status_code == 200


def test_missing_targets_404(client: TestClient) -> None:
    assert client.get("/analytics/posts/99999/performance").status_code == 404
    assert client.get("/analytics/projects/99999/summary").status_code == 404
    assert client.get("/analytics/snapshots/99999").status_code == 404


def test_old_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/posts").status_code == 200
    assert client.get("/post-publications").status_code == 200
