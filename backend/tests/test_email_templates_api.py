"""Тесты REST API email-шаблонов (v0.5.3, offline, sandbox).

Проверяем: auth, список шаблонов, preview (демо/уведомление/дайджест), доступ владельца,
project settings без секретов, test-send-dry (заблокирован по умолчанию, получатель маской).
"""

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


def _notify(db: Session, account, project, owner, **kw):  # noqa: ANN001, ANN003, ANN202
    return NotificationService().create_notification(
        db,
        recipient_user_id=owner.id,
        notification_type="review_assigned",
        title=kw.get("title", "Заголовок"),
        message=kw.get("message", "Сообщение"),
        account_id=account.id,
        project_id=project.id,
        entity_id=1,
    )


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/email-templates").status_code == 401


def test_list_templates(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "eta-list")
    r = client.get("/email-templates", headers=_h(owner.id))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) and len(body) >= 9
    assert {"template_type", "status", "purpose"} <= set(body[0].keys())


def test_preview_demo(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "eta-prev")
    r = client.post(
        "/email-templates/preview", json={"template_type": "digest_daily"}, headers=_h(owner.id)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] and body["text_body"] and body["html_body"]


def test_preview_notification_owner_only(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "eta-own")
    other = user_repository.create_user(db_session, email="other@e.com", password_hash="x")
    db_session.commit()
    n = _notify(db_session, account, project, owner)
    ok = client.post(
        f"/email-templates/notifications/{n['id']}/preview", json={}, headers=_h(owner.id)
    )
    assert ok.status_code == 200
    assert "***" in ok.json()["unsubscribe_url_masked"]
    denied = client.post(
        f"/email-templates/notifications/{n['id']}/preview", json={}, headers=_h(other.id)
    )
    assert denied.status_code == 404


def test_preview_masks_unsubscribe_token(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "eta-mask")
    n = _notify(db_session, account, project, owner)
    r = client.post(
        f"/email-templates/notifications/{n['id']}/preview", json={}, headers=_h(owner.id)
    )
    body = r.json()
    # Маскированный URL присутствует; полный «сырой» токен не отдаётся отдельным полем.
    assert "***" in body["unsubscribe_url_masked"]
    assert "unsubscribe_url" not in body or "***" in str(body.get("unsubscribe_url", ""))


def test_project_settings_no_secrets(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "eta-set")
    r = client.get(f"/email-templates/projects/{project.id}/settings", headers=_h(owner.id))
    assert r.status_code == 200
    body = r.json()
    assert body["smtp_live_send_enabled"] is False
    assert body["notification_email_live_enabled"] is False
    assert body["external_delivery_enabled"] is False
    # Никаких секретов/паролей в ответе.
    assert "smtp_password" not in body
    assert not any("password" in k.lower() for k in body)


def test_test_send_dry_blocked_and_masked(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "eta-ts")
    r = client.post(
        "/email-templates/test-send-dry",
        json={"to": "secretuser@example.ru", "template_type": "system_notice"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["would_send"] is False
    assert body["blocked"] is True
    assert "secretuser" not in body["to_masked"]
    assert "***" in body["to_masked"]
