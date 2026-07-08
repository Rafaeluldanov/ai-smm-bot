"""Тесты REST API публикаций поста."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_publication_platform_registry
from app.integrations.publishing import FakePublishingClient
from app.main import app
from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.publication_platform_registry import PublicationPlatformRegistry


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _post(db: Session, project_id: int, status: str = "approved") -> int:
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            title="Футболки",
            telegram_text="tg",
            vk_text="vk",
            instagram_text="ig",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status=status,
        ),
    ).id


def _use_fake_registry(success: bool = True) -> None:
    app.dependency_overrides[get_publication_platform_registry] = lambda: (
        PublicationPlatformRegistry(
            {
                "telegram": FakePublishingClient("telegram", fail=not success),
                "vk": FakePublishingClient("vk", fail=not success),
            }
        )
    )


def test_list_empty(client: TestClient) -> None:
    response = client.get("/post-publications")
    assert response.status_code == 200
    assert response.json() == []


def test_schedule(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    response = client.post(f"/post-publications/schedule/{post_id}", json={})
    assert response.status_code == 200
    assert response.json()["post_status"] == "scheduled"


def test_schedule_forbidden_409(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "draft")
    response = client.post(f"/post-publications/schedule/{post_id}", json={})
    assert response.status_code == 409


def test_publish(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    client.post(f"/post-publications/schedule/{post_id}", json={})
    _use_fake_registry(success=True)
    response = client.post(f"/post-publications/publish/{post_id}", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["published_count"] == 2
    assert body["post_status"] == "published"


def test_preview_returns_items_without_publishing(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    _use_fake_registry(success=True)

    response = client.post(f"/post-publications/preview/{post_id}", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["post_id"] == post_id
    assert {item["platform"] for item in body["items"]} == {"telegram", "vk"}
    # Расширенные поля preview присутствуют в ответе API.
    vk_item = next(item for item in body["items"] if item["platform"] == "vk")
    assert "media_kind" in vk_item
    assert "media_count" in vk_item
    assert "would_attach_media" in vk_item
    assert "media_warnings" in vk_item
    assert "unsupported_media_reason" in vk_item
    assert vk_item["platform_capabilities"]["platform"] == "vk"
    # preview ничего не публикует
    assert client.get("/post-publications", params={"post_id": post_id}).json() == []


def test_preview_missing_post_404(client: TestClient) -> None:
    _use_fake_registry(success=True)
    assert client.post("/post-publications/preview/99999", json={}).status_code == 404


def test_publish_due_route_ordering(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    client.post(f"/post-publications/schedule/{post_id}", json={})
    _use_fake_registry(success=True)
    # /publish-due не должен перехватываться /{publication_id}.
    response = client.post("/post-publications/publish-due", json={})
    assert response.status_code == 200
    assert response.json()["published_count"] == 2


def test_get_and_patch(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    client.post(f"/post-publications/schedule/{post_id}", json={})
    publication_id = client.get("/post-publications", params={"post_id": post_id}).json()[0]["id"]

    detail = client.get(f"/post-publications/{publication_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == publication_id

    patched = client.patch(f"/post-publications/{publication_id}", json={"target_id": "@newchan"})
    assert patched.status_code == 200
    assert patched.json()["target_id"] == "@newchan"


def test_get_missing_404(client: TestClient) -> None:
    assert client.get("/post-publications/99999").status_code == 404


def test_old_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/posts").status_code == 200
    assert client.get("/post-reviews/99999/card").status_code == 404


def test_platform_capabilities_endpoint(client: TestClient) -> None:
    response = client.get("/post-publications/platform-capabilities")
    assert response.status_code == 200
    body = response.json()
    by_platform = {item["platform"]: item for item in body}
    assert {"vk", "telegram", "instagram", "youtube", "rutube"} <= set(by_platform)
    assert by_platform["vk"]["supports_image_group"] is True
    assert by_platform["vk"]["live_implemented"] is True
    assert by_platform["youtube"]["supports_video"] is True
    assert by_platform["youtube"]["live_implemented"] is False
    assert by_platform["instagram"]["live_flag_name"] == "INSTAGRAM_LIVE_PUBLISHING_ENABLED"
