"""Тесты UI оценки качества медиа (v0.4.6, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "987654321:uiQUALITYsecrettoken"


def test_media_quality_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-quality").text
    assert "Качество медиа" in body
    assert "Preview оценки" in body
    assert "Оценить медиатеку" in body


def test_page_shows_score_dimensions(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-quality").text
    assert "качество" in body and "релевантность" in body
    assert "свежесть" in body and "уник." in body and "платформа" in body


def test_page_warns_no_external_ai_no_live(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-quality").text
    assert "без внешнего" in body.lower()
    assert "live-публикаций" in body.lower()


def test_automation_contains_media_quality_block(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "Оценка качества медиа" in body
    assert "MEDIA_QUALITY_SCORING_WORKER_ENABLED" in body
    assert "/ui/projects/1/media-quality" in body


def test_scheduler_contains_media_quality_block(client: TestClient) -> None:
    body = client.get("/ui/scheduler").text
    assert "Media quality scoring in worker" in body
    assert "media_quality_scoring" in body or "MEDIA_QUALITY_SCORING" in body


def test_no_publish_due_action(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-quality").text
    assert "publish-due" not in body
    assert "publish_due" not in body


def test_ui_has_no_raw_tokens(client: TestClient, db_session: Session) -> None:
    user = user_repository.create_user(db_session, email="uimq@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="uimq", slug="uimq", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="uimq", slug="uimq-proj")
    )
    project.account_id = account.id
    db_session.commit()
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    body = client.get(f"/ui/projects/{project.id}/media-quality").text
    assert _SECRET_TOKEN not in body
    assert "api_key" not in body
