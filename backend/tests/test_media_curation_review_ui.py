"""Тесты UI collaborative review курирования (v0.4.9, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "987654321:uiREVIEWsecrettoken0123456789"


def test_review_board_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-curation-review").text
    assert "Ревью медиатеки" in body
    assert "proposed" in body
    assert "approved" in body


def test_task_detail_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-curation-review/tasks/1").text
    assert "Задача ревью медиатеки" in body
    assert "Комментарии" in body
    assert "timeline" in body.lower()


def test_curation_page_links_review(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-curation").text
    assert "/ui/projects/1/media-curation-review" in body


def test_automation_contains_review_flags(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "Media curation review" in body
    assert "MEDIA_CURATION_REVIEW_ENABLED" in body
    assert "MEDIA_CURATION_REVIEW_REQUIRE_APPROVAL" in body
    assert "MEDIA_CURATION_REVIEW_AUTO_APPLY_AFTER_APPROVAL" in body
    assert "MEDIA_CURATION_REVIEW_NOTIFY_ENABLED" in body


def test_dashboard_shows_review_link(client: TestClient) -> None:
    body = client.get("/ui/projects/1/dashboard").text
    assert "/ui/projects/1/media-curation-review" in body
    assert "Ревью медиатеки" in body


def test_page_warns_no_delete_no_ai(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-curation-review").text
    assert "не удаляются" in body.lower()
    assert "после одобрения" in body.lower() or "approved" in body.lower()


def test_no_delete_button(client: TestClient) -> None:
    for path in (
        "/ui/projects/1/media-curation-review",
        "/ui/projects/1/media-curation-review/tasks/1",
    ):
        body = client.get(path).text
        assert "Удалить файл" not in body
        assert "delete-media" not in body
        assert "delete-file" not in body


def test_no_publish_due_action(client: TestClient) -> None:
    for path in (
        "/ui/projects/1/media-curation-review",
        "/ui/projects/1/media-curation-review/tasks/1",
    ):
        body = client.get(path).text
        assert "publish-due" not in body
        assert "publish_due" not in body


def test_ui_has_no_raw_tokens(client: TestClient, db_session: Session) -> None:
    user = user_repository.create_user(db_session, email="uirev@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="uirev", slug="uirev", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="uirev", slug="uirev-proj")
    )
    project.account_id = account.id
    db_session.commit()
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    body = client.get(f"/ui/projects/{project.id}/media-curation-review").text
    assert _SECRET_TOKEN not in body
    assert "api_key" not in body
    assert "disk:/" not in body
