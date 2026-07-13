"""Тесты REST API Telegram webhook/polling sandbox (v0.5.5, offline)."""

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.core.security import make_dev_token
from app.main import app
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_telegram_binding_service import (
    NotificationTelegramBindingService,
)


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _token(db: Session, owner, account) -> str:  # noqa: ANN001
    res = NotificationTelegramBindingService().create_binding_token(
        db, owner.id, account_id=account.id
    )
    return res["verification_token"]


def test_webhook_no_auth_works(client: TestClient, db_session: Session) -> None:
    account, _p, owner = _seed(db_session, "twa-wh")
    token = _token(db_session, owner, account)
    r = client.post(
        "/notification-telegram/webhook",
        json={
            "update_id": 1,
            "message": {"text": f"/start {token}", "chat": {"id": 987654321}, "from": {"id": 5}},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "verified_binding"
    assert "987654321" not in r.text
    assert token not in r.text


def test_webhook_ignores_bad_json(client: TestClient) -> None:
    r = client.post(
        "/notification-telegram/webhook",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200


def test_simulate_update_requires_auth(client: TestClient) -> None:
    assert (
        client.post(
            "/notification-telegram/simulate-update", json={"token": "x", "chat_id": "1"}
        ).status_code
        == 401
    )


def test_updates_list_sanitized(client: TestClient, db_session: Session) -> None:
    account, _p, owner = _seed(db_session, "twa-upd")
    token = _token(db_session, owner, account)
    client.post(
        "/notification-telegram/simulate-update",
        json={"token": token, "chat_id": "123456789", "username": "ivan"},
        headers=_h(owner.id),
    )
    r = client.get("/notification-telegram/updates", headers=_h(owner.id))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert "123456789" not in r.text
    assert token not in r.text


def test_project_dashboard_requires_access(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "twa-dash")
    r = client.get(
        f"/notification-telegram/projects/{project.id}/webhook-dashboard", headers=_h(owner.id)
    )
    assert r.status_code == 200
    assert r.json()["flags"]["webhook_live_enabled"] is False


def test_management_dry_endpoints(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "twa-mgmt")
    assert (
        client.post("/notification-telegram/webhook/set-dry", json={}, headers=_h(owner.id)).json()[
            "dry_run"
        ]
        is True
    )
    assert (
        client.get("/notification-telegram/webhook/info-dry", headers=_h(owner.id)).json()["method"]
        == "getWebhookInfo"
    )
    assert (
        client.post(
            "/notification-telegram/polling/dry", json={"limit": 5}, headers=_h(owner.id)
        ).json()["would_send"]["limit"]
        == 5
    )


def test_webhook_invalid_secret_403(session_factory: sessionmaker[Session]) -> None:
    from app.api.deps import get_db, get_telegram_incoming_service
    from app.services.telegram_incoming_service import TelegramIncomingService

    settings = Settings(
        notification_telegram_webhook_secret_required=True,
        notification_telegram_webhook_secret_token="expected-secret",
    )

    def override_get_db() -> Iterator[Session]:
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_telegram_incoming_service] = lambda: TelegramIncomingService(
        settings=settings
    )
    try:
        with TestClient(app) as c:
            r = c.post(
                "/notification-telegram/webhook",
                json={"update_id": 1, "message": {"text": "/help", "chat": {"id": 1}}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            )
            assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
