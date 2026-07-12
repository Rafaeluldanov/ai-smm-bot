"""Тесты UI доставки уведомлений/дайджестов (v0.5.1, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "987654321:uiDELIVERYsecrettoken0123456789"


def test_delivery_page_renders(client: TestClient) -> None:
    body = client.get("/ui/notification-delivery").text
    assert "Доставка уведомлений" in body
    assert "Логи доставки" in body


def test_digests_page_renders(client: TestClient) -> None:
    body = client.get("/ui/notification-digests").text
    assert "Дайджесты" in body


def test_project_delivery_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/notification-delivery").text
    assert "Доставка уведомлений проекта" in body


def test_external_disabled_banner(client: TestClient) -> None:
    body = client.get("/ui/notification-delivery").text.lower()
    assert "внешняя доставка выключена" in body


def test_settings_has_delivery_preferences(client: TestClient) -> None:
    body = client.get("/ui/settings").text
    assert "notif-prefs" in body
    assert "np-telegram" in body
    assert "/ui/notification-delivery" in body


def test_no_publish_due_action(client: TestClient) -> None:
    for path in ("/ui/notification-delivery", "/ui/notification-digests"):
        body = client.get(path).text
        assert "publish-due" not in body
        assert "publish_due" not in body


def test_no_live_send_button(client: TestClient) -> None:
    body = client.get("/ui/notification-delivery").text
    # Только sandbox/dry-run кнопки; никаких "Отправить live/реально".
    assert "dry-run" in body.lower() or "Send dry-run" in body
    assert "Отправить реально" not in body


def test_ui_has_no_raw_tokens(client: TestClient, db_session: Session) -> None:
    user = user_repository.create_user(db_session, email="uidlv@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="uidlv", slug="uidlv", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="uidlv", slug="uidlv-proj")
    )
    project.account_id = account.id
    db_session.commit()
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    body = client.get(f"/ui/projects/{project.id}/notification-delivery").text
    assert _SECRET_TOKEN not in body
    assert "api_key" not in body
