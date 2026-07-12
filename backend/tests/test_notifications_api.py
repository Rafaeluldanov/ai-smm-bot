"""Тесты REST API уведомлений (v0.5.0, offline). Пользователь видит только свои уведомления."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_service import NotificationService
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "123456789:notifSECRETtelegramTOKEN0123456789"


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
        notification_type=kw.get("notification_type", "system_notice"),
        title=kw.get("title", "Заголовок"),
        message=kw.get("message", "Сообщение"),
        account_id=account.id,
        project_id=project.id,
        entity_id=kw.get("entity_id", 1),
    )


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_current_user_sees_own_notifications(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "na-own")
    _notify(db_session, account, project, owner)
    token = make_dev_token(owner.id)
    r = client.get("/notifications", headers=_h(token))
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_unread_count(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "na-unread")
    _notify(db_session, account, project, owner, entity_id=1)
    _notify(db_session, account, project, owner, entity_id=2)
    token = make_dev_token(owner.id)
    r = client.get("/notifications/unread-count", headers=_h(token))
    assert r.status_code == 200 and r.json()["unread_count"] == 2


def test_requires_auth(client: TestClient, db_session: Session) -> None:
    assert client.get("/notifications").status_code == 401
    assert client.get("/notifications/unread-count").status_code == 401


def test_mark_read_and_dismiss(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "na-read")
    v = _notify(db_session, account, project, owner)
    token = make_dev_token(owner.id)
    rr = client.post(f"/notifications/{v['id']}/read", json={}, headers=_h(token))
    assert rr.status_code == 200 and rr.json()["status"] == "read"
    rd = client.post(f"/notifications/{v['id']}/dismiss", json={}, headers=_h(token))
    assert rd.status_code == 200 and rd.json()["status"] == "dismissed"


def test_cannot_mark_another_users_notification(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "na-iso1")
    _account2, _project2, other = _seed(db_session, "na-iso2")
    v = _notify(db_session, account, project, owner)
    other_token = make_dev_token(other.id)
    r = client.post(f"/notifications/{v['id']}/read", json={}, headers=_h(other_token))
    assert r.status_code == 404


def test_read_all(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "na-allread")
    _notify(db_session, account, project, owner, entity_id=1)
    _notify(db_session, account, project, owner, entity_id=2)
    token = make_dev_token(owner.id)
    r = client.post("/notifications/read-all", json={}, headers=_h(token))
    assert r.status_code == 200 and r.json()["marked_read"] == 2


def test_preferences_get_set(client: TestClient, db_session: Session) -> None:
    _account, _project, owner = _seed(db_session, "na-prefs")
    token = make_dev_token(owner.id)
    g = client.get("/notifications/preferences", headers=_h(token))
    assert g.status_code == 200 and g.json()["in_app_enabled"] is True
    assert g.json()["external_delivery_enabled"] is False
    # email нельзя включить без внешней доставки — сервис принудительно выключает.
    s = client.post(
        "/notifications/preferences",
        json={"channel": "email", "enabled": True},
        headers=_h(token),
    )
    assert s.status_code == 200 and s.json()["enabled"] is False


def test_project_dashboard_requires_access(client: TestClient, db_session: Session) -> None:
    _a1, p1, _o1 = _seed(db_session, "na-dash1")
    _a2, _p2, o2 = _seed(db_session, "na-dash2")
    t2 = make_dev_token(o2.id)
    assert (
        client.get(f"/notifications/projects/{p1.id}/dashboard", headers=_h(t2)).status_code == 404
    )


def test_project_workload_and_overdue_scan(client: TestClient, db_session: Session) -> None:
    _account, project, owner = _seed(db_session, "na-wl")
    token = make_dev_token(owner.id)
    w = client.get(f"/notifications/projects/{project.id}/workload", headers=_h(token))
    assert w.status_code == 200 and "reviewers" in w.json()
    sc = client.post(
        f"/notifications/projects/{project.id}/overdue-scan-dry", json={}, headers=_h(token)
    )
    assert sc.status_code == 200 and sc.json()["dry_run"] is True


def test_no_secrets_in_responses(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "na-nosec")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    _notify(db_session, account, project, owner, message=f"secret {_SECRET_TOKEN} disk:/x.jpg")
    token = make_dev_token(owner.id)
    body = client.get("/notifications", headers=_h(token)).text
    assert _SECRET_TOKEN not in body
    assert "disk:/" not in body
