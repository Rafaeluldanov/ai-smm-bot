"""Тесты UI fingerprint/дублей медиа (v0.4.7, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "987654321:uiFPsecrettoken"


def test_fingerprints_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-fingerprints").text
    assert "Fingerprint медиа" in body
    assert "Preview fingerprints" in body
    assert "Рассчитать fingerprints" in body


def test_duplicates_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-duplicates").text
    assert "Дубли и похожие медиа" in body
    assert "Построить кластеры" in body
    assert "Файлы НЕ удаляются" in body


def test_page_warns_no_external_ai_no_delete(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-fingerprints").text
    assert "без внешнего" in body.lower()
    fp_dup = client.get("/ui/projects/1/media-duplicates").text
    assert "не удаляются" in fp_dup.lower()


def test_automation_contains_fingerprint_block(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "Fingerprint и дубли медиа" in body
    assert "MEDIA_FINGERPRINTING_WORKER_ENABLED" in body
    assert "/ui/projects/1/media-fingerprints" in body


def test_scheduler_contains_fingerprint_block(client: TestClient) -> None:
    body = client.get("/ui/scheduler").text
    assert "Fingerprint и дубли медиа в worker" in body
    assert "media_fingerprinting" in body or "MEDIA_FINGERPRINTING" in body


def test_no_delete_action(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-duplicates").text
    assert "Удалить файл" not in body
    assert "delete-file" not in body


def test_no_publish_due_action(client: TestClient) -> None:
    for path in ("/ui/projects/1/media-fingerprints", "/ui/projects/1/media-duplicates"):
        body = client.get(path).text
        assert "publish-due" not in body
        assert "publish_due" not in body


def test_ui_has_no_raw_tokens(client: TestClient, db_session: Session) -> None:
    user = user_repository.create_user(db_session, email="uifp@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="uifp", slug="uifp", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="uifp", slug="uifp-proj")
    )
    project.account_id = account.id
    db_session.commit()
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    body = client.get(f"/ui/projects/{project.id}/media-fingerprints").text
    assert _SECRET_TOKEN not in body
    assert "api_key" not in body
