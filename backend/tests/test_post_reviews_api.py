"""Тесты REST API согласования постов."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import media_asset_repository as media_repo
from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _media(db: Session, project_id: int) -> int:
    return media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="f.jpg",
            yandex_disk_path="disk:/f.jpg",
            status="approved",
            tags={"products": ["футболка"]},
        ),
    ).id


def _post(db: Session, project_id: int, status: str = "draft", media: bool = True) -> int:
    media_id = _media(db, project_id) if media else None
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            media_asset_id=media_id,
            title="Футболки",
            telegram_text="t",
            vk_text="v",
            instagram_text="i",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status=status,
        ),
    ).id


def test_get_card(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    response = client.get(f"/post-reviews/{post_id}/card")
    assert response.status_code == 200
    assert response.json()["post_id"] == post_id


def test_get_timeline(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    response = client.get(f"/post-reviews/{post_id}/timeline")
    assert response.status_code == 200
    assert response.json()["current_status"] == "draft"


def test_submit(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, status="draft")
    response = client.post(f"/post-reviews/{post_id}/submit", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"


def test_approve(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, status="needs_review")
    response = client.post(f"/post-reviews/{post_id}/approve", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_reject(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, status="draft")
    response = client.post(f"/post-reviews/{post_id}/reject", json={"comment": "Не то"})
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_request_changes(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, status="needs_review")
    response = client.post(f"/post-reviews/{post_id}/request-changes", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "draft"


def test_return_to_draft(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, status="rejected")
    response = client.post(f"/post-reviews/{post_id}/return-to-draft", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "draft"


def test_edit(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, status="draft")
    response = client.patch(f"/post-reviews/{post_id}/edit", json={"telegram_text": "НОВЫЙ ТЕКСТ"})
    assert response.status_code == 200
    assert response.json()["telegram_text"] == "НОВЫЙ ТЕКСТ"


def test_comment(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, status="draft")
    response = client.post(
        f"/post-reviews/{post_id}/comment", json={"comment": "Поправьте заголовок"}
    )
    assert response.status_code == 200
    assert response.json()["action"] == "comment"


def test_telegram_preview(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, status="needs_review")
    response = client.get(f"/post-reviews/{post_id}/telegram-preview")
    assert response.status_code == 200
    body = response.json()
    assert body["post_id"] == post_id
    assert "Статус: needs_review" in body["text"]
    assert len(body["buttons"]) > 0


def test_missing_post_404(client: TestClient) -> None:
    assert client.get("/post-reviews/99999/card").status_code == 404


def test_forbidden_transition_409(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, status="rejected")
    response = client.post(f"/post-reviews/{post_id}/approve", json={})
    assert response.status_code == 409


def test_old_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/posts").status_code == 200
    assert client.get("/topics").status_code == 200
