"""Тесты REST API постов и генерации."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import post_repository as post_repo
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import create_topic
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate


def _teeon(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _topic(db: Session, project_id: int) -> int:
    return create_topic(
        db,
        TopicCreate(
            project_id=project_id,
            title="Футболки с логотипом на заказ",
            cluster="футболки",
            seo_keywords=["футболки с логотипом"],
            status="recommended",
        ),
    ).id


def _draft_post(db: Session, project_id: int, topic_id: int) -> int:
    return post_repo.create_post(
        db,
        PostCreate(
            project_id=project_id,
            topic_id=topic_id,
            title="Футболки",
            telegram_text="t",
            vk_text="v",
            instagram_text="i",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status="draft",
        ),
    ).id


def test_list_posts_empty(client: TestClient) -> None:
    response = client.get("/posts")
    assert response.status_code == 200
    assert response.json() == []


def test_generate_topic_and_route_ordering(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    topic_id = _topic(db_session, project_id)
    # /posts/generate/topic/{id} не должен перехватываться /posts/{post_id}.
    response = client.post(f"/posts/generate/topic/{topic_id}", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["post"]["title"] == "Футболки с логотипом на заказ"
    assert body["post"]["status"] in {"draft", "needs_media"}


def test_generate_topic_404(client: TestClient) -> None:
    assert client.post("/posts/generate/topic/99999", json={}).status_code == 404


def test_generate_weekly_plan(client: TestClient, db_session: Session) -> None:
    _teeon(db_session)
    response = client.post(
        "/posts/generate/weekly-plan", json={"project_slug": "teeon", "posts_per_week": 3}
    )
    assert response.status_code == 200
    assert response.json()["generated_count"] == 3


def test_generate_weekly_plan_404(client: TestClient) -> None:
    response = client.post("/posts/generate/weekly-plan", json={"project_id": 99999})
    assert response.status_code == 404


def test_get_post_and_404(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _draft_post(db_session, project_id, topic_id)

    detail = client.get(f"/posts/{post_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == post_id
    assert client.get("/posts/99999").status_code == 404


def test_patch_post(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _draft_post(db_session, project_id, topic_id)

    response = client.patch(f"/posts/{post_id}", json={"title": "Новый заголовок"})
    assert response.status_code == 200
    assert response.json()["title"] == "Новый заголовок"


def test_patch_status_approved(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _draft_post(db_session, project_id, topic_id)

    response = client.patch(f"/posts/{post_id}/status", json={"status": "approved"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_patch_status_unknown_422(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _draft_post(db_session, project_id, topic_id)

    response = client.patch(f"/posts/{post_id}/status", json={"status": "bogus"})
    assert response.status_code == 422


def test_patch_status_forbidden_409(client: TestClient, db_session: Session) -> None:
    project_id = _teeon(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _draft_post(db_session, project_id, topic_id)

    response = client.patch(f"/posts/{post_id}/status", json={"status": "scheduled"})
    assert response.status_code == 409


def test_old_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/projects").status_code == 200
    assert client.get("/media-assets").status_code == 200
    assert client.get("/topics").status_code == 200
