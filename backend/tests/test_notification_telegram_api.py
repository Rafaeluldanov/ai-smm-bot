"""Тесты REST API Telegram-канала уведомлений (v0.5.4, offline, sandbox)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_service import NotificationService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _notify(db: Session, account, project, owner):  # noqa: ANN001, ANN202
    return NotificationService().create_notification(
        db,
        recipient_user_id=owner.id,
        notification_type="review_assigned",
        title="Заголовок",
        message="Сообщение",
        account_id=account.id,
        project_id=project.id,
        entity_id=1,
    )


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/notification-telegram/bindings").status_code == 401


def test_create_and_verify_binding(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "tga-cv")
    cr = client.post("/notification-telegram/bindings", json={}, headers=_h(owner.id))
    assert cr.status_code == 200
    body = cr.json()
    assert "verification_token" in body and body["verification_token_prefix"]
    vr = client.post(
        "/notification-telegram/bindings/verify",
        json={"token": body["verification_token"], "chat_id": "123456789", "username": "u"},
        headers=_h(owner.id),
    )
    assert vr.status_code == 200
    v = vr.json()
    assert v["verified"] is True
    assert "***" in v["chat_id_masked"]
    assert "123456789" not in str(v)


def test_list_bindings(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "tga-list")
    client.post("/notification-telegram/bindings", json={}, headers=_h(owner.id))
    r = client.get("/notification-telegram/bindings", headers=_h(owner.id))
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_preview_notification(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "tga-prev")
    n = _notify(db_session, account, project, owner)
    r = client.post(
        f"/notification-telegram/notifications/{n['id']}/preview", json={}, headers=_h(owner.id)
    )
    assert r.status_code == 200
    assert r.json()["text"]


def test_send_dry_blocks_without_binding(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "tga-nob")
    n = _notify(db_session, account, project, owner)
    r = client.post(
        f"/notification-telegram/notifications/{n['id']}/send-dry", headers=_h(owner.id)
    )
    # Задача создаётся (disabled из-за отсутствия привязки), dry-run → skipped/disabled.
    assert r.status_code == 200
    assert r.json()["outcome"] in {"skipped", "disabled"}


def test_test_send_dry_blocked_by_default(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "tga-ts")
    r = client.post(
        "/notification-telegram/test-send-dry",
        json={"template_type": "system_notice"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["would_send"] is False
    assert body["blocked"] is True


def test_user_cannot_access_other_binding(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "tga-own")
    other = user_repository.create_user(db_session, email="other@e.com", password_hash="x")
    db_session.commit()
    cr = client.post("/notification-telegram/bindings", json={}, headers=_h(owner.id)).json()
    view = client.post(
        "/notification-telegram/bindings/verify",
        json={"token": cr["verification_token"], "chat_id": "111222333"},
        headers=_h(owner.id),
    ).json()
    denied = client.post(
        f"/notification-telegram/bindings/{view['id']}/disable", headers=_h(other.id)
    )
    assert denied.status_code == 404


def test_project_dashboard_no_secrets(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "tga-dash")
    r = client.get(f"/notification-telegram/projects/{project.id}/dashboard", headers=_h(owner.id))
    assert r.status_code == 200
    body = r.json()
    assert body["flags"]["live_send_enabled"] is False
    assert body["flags"]["external_delivery_enabled"] is False
    assert "bot_token" not in str(body)
    assert not any("bot_token" in k.lower() for k in body.get("flags", {}))
