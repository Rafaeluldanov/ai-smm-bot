"""Тесты REST API доставки уведомлений/дайджестов (v0.5.1, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_service import NotificationService
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "123456789:deliverySECRETtelegram0123456789"


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
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
        entity_id=kw.get("entity_id", 1),
    )


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/notification-delivery/logs").status_code == 401
    assert client.get("/notification-digests").status_code == 401


def test_preview_and_send_dry(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "da-prev")
    n = _notify(db_session, account, project, owner)
    token = make_dev_token(owner.id)
    pv = client.post(
        f"/notification-delivery/notifications/{n['id']}/preview",
        json={"channels": ["email", "telegram"]},
        headers=_h(token),
    )
    assert pv.status_code == 200 and len(pv.json()["previews"]) == 2
    sd = client.post(
        f"/notification-delivery/notifications/{n['id']}/send-dry",
        json={"channels": ["email"]},
        headers=_h(token),
    )
    assert sd.status_code == 200 and sd.json()["results"][0]["outcome"] == "skipped"


def test_list_own_logs(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "da-logs")
    n = _notify(db_session, account, project, owner)
    token = make_dev_token(owner.id)
    client.post(
        f"/notification-delivery/notifications/{n['id']}/send-dry",
        json={"channels": ["email"]},
        headers=_h(token),
    )
    r = client.get("/notification-delivery/logs", headers=_h(token))
    assert r.status_code == 200 and len(r.json()) >= 1


def test_send_refuses_when_external_disabled(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "da-refuse")
    n = _notify(db_session, account, project, owner)
    from app.services.notification_delivery_service import NotificationDeliveryService

    log = NotificationDeliveryService().create_delivery_job(db_session, n["id"], "email")
    token = make_dev_token(owner.id)
    r = client.post(f"/notification-delivery/logs/{log.id}/send", json={}, headers=_h(token))
    assert r.status_code == 403


def test_retry_dry(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "da-retry")
    n = _notify(db_session, account, project, owner)
    from app.services.notification_delivery_service import NotificationDeliveryService

    log = NotificationDeliveryService().create_delivery_job(db_session, n["id"], "email")
    token = make_dev_token(owner.id)
    r = client.post(f"/notification-delivery/logs/{log.id}/retry-dry", json={}, headers=_h(token))
    assert r.status_code == 200 and r.json()["outcome"] == "skipped"


def test_project_dashboard_requires_access(client: TestClient, db_session: Session) -> None:
    _a1, p1, _o1 = _seed(db_session, "da-dash1")
    _a2, _p2, o2 = _seed(db_session, "da-dash2")
    t2 = make_dev_token(o2.id)
    assert (
        client.get(f"/notification-delivery/projects/{p1.id}/dashboard", headers=_h(t2)).status_code
        == 404
    )


def test_digest_preview_and_generate_dry(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "da-digest")
    _notify(db_session, account, project, owner)
    token = make_dev_token(owner.id)
    pv = client.post(
        "/notification-digests/preview", json={"frequency": "daily"}, headers=_h(token)
    )
    assert pv.status_code == 200 and "subject" in pv.json()
    gd = client.post(
        "/notification-digests/generate-dry", json={"frequency": "daily"}, headers=_h(token)
    )
    assert gd.status_code == 200 and gd.json()["digest_id"] is None


def test_digest_generate_disabled_by_default(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "da-gendis")
    _notify(db_session, account, project, owner)
    token = make_dev_token(owner.id)
    r = client.post(
        "/notification-digests/generate", json={"frequency": "daily"}, headers=_h(token)
    )
    assert r.status_code == 200 and r.json().get("disabled") is True


def test_scheduler_dry(client: TestClient, db_session: Session) -> None:
    _account, _project, owner = _seed(db_session, "da-sched")
    token = make_dev_token(owner.id)
    r = client.post(
        "/notification-digests/scheduler-dry", json={"frequency": "daily"}, headers=_h(token)
    )
    assert r.status_code == 200 and r.json()["dry_run"] is True


def test_no_secrets_in_responses(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "da-nosec")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    n = _notify(db_session, account, project, owner, message=f"secret {_SECRET_TOKEN} disk:/x.jpg")
    token = make_dev_token(owner.id)
    client.post(
        f"/notification-delivery/notifications/{n['id']}/send-dry",
        json={"channels": ["email"]},
        headers=_h(token),
    )
    body = client.get("/notification-delivery/logs", headers=_h(token)).text
    assert _SECRET_TOKEN not in body
    assert "disk:/" not in body
