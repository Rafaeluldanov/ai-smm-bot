"""Тесты UI safety-слоя уведомлений (v0.5.2, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import (
    account_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    notification_safety_repository as safety_repo,
)
from app.schemas.project import ProjectCreate
from app.services.webhook_subscription_service import WebhookSubscriptionService

_URL = "https://hooks.example.com/secret/endpoint"
_SECRET = "verysecretsigningkey0123456789"


def test_safety_page_renders(client: TestClient) -> None:
    body = client.get("/ui/notification-safety").text
    assert "Безопасность уведомлений" in body
    assert "Отписки" in body


def test_preferences_page_renders(client: TestClient) -> None:
    body = client.get("/ui/notification-preferences").text
    assert "Настройки уведомлений" in body


def test_webhooks_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/webhooks").text
    assert "Webhook-подписки" in body


def test_project_safety_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/notification-safety").text
    assert "Безопасность уведомлений проекта" in body


def test_external_disabled_banner(client: TestClient) -> None:
    body = client.get("/ui/notification-safety").text.lower()
    assert "внешняя доставка выключена" in body


def test_live_webhook_disabled_notice(client: TestClient) -> None:
    body = client.get("/ui/projects/1/webhooks").text.lower()
    assert "выключен" in body  # реальный вызов webhook выключен


def test_settings_has_safety_links(client: TestClient) -> None:
    body = client.get("/ui/settings").text
    assert "/ui/notification-safety" in body
    assert "/ui/notification-preferences" in body


def test_no_publish_due(client: TestClient) -> None:
    for path in (
        "/ui/notification-safety",
        "/ui/projects/1/webhooks",
        "/ui/notification-preferences",
    ):
        body = client.get(path).text
        assert "publish-due" not in body and "publish_due" not in body


def test_webhook_secret_masked_no_raw(client: TestClient, db_session: Session) -> None:
    user = user_repository.create_user(db_session, email="uiwh@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="uiwh", slug="uiwh", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="uiwh", slug="uiwh-proj")
    )
    project.account_id = account.id
    db_session.commit()
    WebhookSubscriptionService().create_subscription(
        db_session, account.id, "h", _URL, project_id=project.id, signing_secret=_SECRET
    )
    # UI-страница webhooks не содержит сырых URL/secret (данные грузятся через API).
    body = client.get(f"/ui/projects/{project.id}/webhooks").text
    assert _SECRET not in body and _URL not in body
    # И сам delivery-view не раскрывает сырьё.
    rows = safety_repo.list_webhook_subscriptions(db_session, account_id=account.id)
    assert rows and _URL not in (rows[0].url_masked or "")
