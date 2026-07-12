"""Тесты UI курирования медиатеки (v0.4.8, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "987654321:uiCURATIONsecrettoken"


def test_curation_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-curation").text
    assert "Очистка и разметка медиатеки" in body
    assert "Preview задач" in body
    assert "Сгенерировать задачи" in body


def test_curation_task_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-curation/tasks/1").text
    assert "Задача курирования" in body


def test_page_warns_no_delete_no_ai(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-curation").text
    assert "не удаляются" in body.lower()
    assert "после подтверждения" in body.lower()


def test_quality_page_links_curation(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-quality").text
    assert "/ui/projects/1/media-curation" in body


def test_duplicates_page_links_curation(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-duplicates").text
    assert "/ui/projects/1/media-curation" in body


def test_automation_contains_curation_flags(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "Media curation worker" in body
    assert "MEDIA_CURATION_WORKER_ENABLED" in body
    assert "MEDIA_CURATION_AUTO_DELETE_ENABLED" in body


def test_scheduler_contains_curation_block(client: TestClient) -> None:
    body = client.get("/ui/scheduler").text
    assert "Курирование медиатеки в worker" in body
    assert "media_curation" in body or "MEDIA_CURATION" in body


def test_no_delete_button(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-curation").text
    assert "Удалить файл" not in body
    assert "delete-media" not in body
    assert "delete-file" not in body


def test_no_publish_due_action(client: TestClient) -> None:
    for path in ("/ui/projects/1/media-curation", "/ui/projects/1/media-curation/tasks/1"):
        body = client.get(path).text
        assert "publish-due" not in body
        assert "publish_due" not in body


def test_ui_has_no_raw_tokens(client: TestClient, db_session: Session) -> None:
    user = user_repository.create_user(db_session, email="uicur@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="uicur", slug="uicur", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="uicur", slug="uicur-proj")
    )
    project.account_id = account.id
    db_session.commit()
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    body = client.get(f"/ui/projects/{project.id}/media-curation").text
    assert _SECRET_TOKEN not in body
    assert "api_key" not in body
