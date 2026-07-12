"""Тесты UI уведомлений (v0.5.0, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "987654321:uiNOTIFsecrettoken0123456789"


def test_notifications_page_renders(client: TestClient) -> None:
    body = client.get("/ui/notifications").text
    assert "Уведомления" in body
    assert "Прочитать все" in body


def test_project_notifications_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/notifications").text
    assert "Уведомления проекта" in body
    assert "Overdue" in body


def test_review_workload_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/review-workload").text
    assert "Нагрузка ревьюеров" in body
    assert "SLA" in body


def test_notification_bell_present(client: TestClient) -> None:
    body = client.get("/ui/notifications").text
    assert "notif-bell" in body
    assert "notif-count" in body
    assert "/notifications/unread-count" in body


def test_settings_has_notification_preferences(client: TestClient) -> None:
    body = client.get("/ui/settings").text
    assert "notif-prefs" in body
    assert "in-app" in body.lower()


def test_no_external_delivery_claim(client: TestClient) -> None:
    for path in ("/ui/notifications", "/ui/projects/1/notifications", "/ui/settings"):
        body = client.get(path).text.lower()
        assert "выключен" in body or "нет" in body  # заявлено, что внешней доставки нет


def test_no_publish_due_action(client: TestClient) -> None:
    for path in (
        "/ui/notifications",
        "/ui/projects/1/notifications",
        "/ui/projects/1/review-workload",
    ):
        body = client.get(path).text
        assert "publish-due" not in body
        assert "publish_due" not in body


def test_ui_has_no_raw_tokens(client: TestClient, db_session: Session) -> None:
    user = user_repository.create_user(db_session, email="uinotif@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="uinotif", slug="uinotif", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="uinotif", slug="uinotif-proj")
    )
    project.account_id = account.id
    db_session.commit()
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    body = client.get(f"/ui/projects/{project.id}/notifications").text
    assert _SECRET_TOKEN not in body
    assert "api_key" not in body
    assert "disk:/" not in body
