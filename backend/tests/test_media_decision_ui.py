"""Тесты UI автовыбора медиа (v0.4.5, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "987654321:uiMEDIAdecisionSECRETtoken"


def test_media_decisions_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-decisions").text
    assert "Выбор медиа по обучению" in body
    assert "Preview следующего медиа" in body
    assert "Создать решение" in body


def test_page_warns_no_live_publish_and_public_url(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-decisions").text
    assert "live не выполняется" in body.lower()
    assert "public image_url" in body


def test_detail_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-decisions/1").text
    assert "Почему бот выбрал эти медиа" in body
    assert "Причины" in body and "Альтернативы" in body


def test_automation_contains_auto_media_block(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "Автовыбор медиа" in body
    assert "AUTO_MEDIA_SELECTION_WORKER_ENABLED" in body
    assert "/ui/projects/1/media-decisions" in body


def test_scheduler_contains_auto_media_worker_block(client: TestClient) -> None:
    body = client.get("/ui/scheduler").text
    assert "Автовыбор медиа в worker" in body
    assert "auto_media_selection" in body or "AUTO_MEDIA_SELECTION" in body


def test_dashboard_has_next_media_card(client: TestClient) -> None:
    body = client.get("/ui/projects/1/dashboard").text
    assert "Следующее медиа" in body
    assert "/ui/projects/1/media-decisions" in body


def test_no_publish_due_action(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-decisions").text
    assert "publish-due" not in body
    assert "publish_due" not in body


def test_ui_has_no_raw_tokens(client: TestClient, db_session: Session) -> None:
    user = user_repository.create_user(db_session, email="uimd@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="uimd", slug="uimd", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="uimd", slug="uimd-proj")
    )
    project.account_id = account.id
    db_session.commit()
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    body = client.get(f"/ui/projects/{project.id}/media-decisions").text
    assert _SECRET_TOKEN not in body
    assert "api_key" not in body
