"""Тесты REST API safety-слоя уведомлений (v0.5.2, offline)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_unsubscribe_service import NotificationUnsubscribeService

_URL = "https://hooks.example.com/endpoint/xyz"
_SECRET = "topsecretvalue0123456789"


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/notification-safety/opt-outs").status_code == 401
    assert client.get("/notification-safety/suppressions").status_code == 401


def test_opt_outs_crud(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "sa-oo")
    token = make_dev_token(owner.id)
    created = client.post(
        "/notification-safety/opt-outs",
        json={"scope": "channel", "channel": "email"},
        headers=_h(token),
    )
    assert created.status_code == 200 and created.json()["scope"] == "channel"
    oid = created.json()["id"]
    lst = client.get("/notification-safety/opt-outs", headers=_h(token))
    assert lst.status_code == 200 and len(lst.json()) == 1
    rev = client.post(f"/notification-safety/opt-outs/{oid}/revoke", json={}, headers=_h(token))
    assert rev.status_code == 200 and rev.json()["status"] == "revoked"


def test_rate_limit_check(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "sa-rl")
    token = make_dev_token(owner.id)
    r = client.post(
        "/notification-safety/rate-limits/check", json={"channel": "email"}, headers=_h(token)
    )
    assert r.status_code == 200 and r.json()["allowed"] is True
    d = client.get("/notification-safety/rate-limits", headers=_h(token))
    assert d.status_code == 200 and "buckets" in d.json()


def test_suppressions_list_clear(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "sa-sup")
    from app.services.notification_suppression_service import NotificationSuppressionService

    svc = NotificationSuppressionService()
    r = svc.record_delivery_failure(db_session, owner.id, "email", destination="x@e.ru")
    token = make_dev_token(owner.id)
    lst = client.get("/notification-safety/suppressions", headers=_h(token))
    assert lst.status_code == 200
    cl = client.post(
        f"/notification-safety/suppressions/{r['suppression_id']}/clear", json={}, headers=_h(token)
    )
    assert cl.status_code == 200 and cl.json()["status"] == "cleared"


def test_webhook_crud_and_masked(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "sa-wh")
    token = make_dev_token(owner.id)
    created = client.post(
        "/notification-safety/webhooks",
        json={
            "account_id": account.id,
            "title": "h",
            "url": _URL,
            "project_id": project.id,
            "signing_secret": _SECRET,
        },
        headers=_h(token),
    )
    assert created.status_code == 200
    body = created.json()
    assert _URL not in str(body) and _SECRET not in str(body)
    assert body["url_masked"].endswith("/***")
    sid = body["id"]
    got = client.get(f"/notification-safety/webhooks/{sid}", headers=_h(token))
    assert got.status_code == 200
    pv = client.post(f"/notification-safety/webhooks/{sid}/preview", json={}, headers=_h(token))
    assert pv.status_code == 200 and pv.json()["would_send"] is False
    rev = client.post(f"/notification-safety/webhooks/{sid}/revoke", json={}, headers=_h(token))
    assert rev.status_code == 200 and rev.json()["status"] == "revoked"


def test_webhook_cross_account_denied(client: TestClient, db_session: Session) -> None:
    a1, p1, o1 = _seed(db_session, "sa-iso1")
    _a2, _p2, o2 = _seed(db_session, "sa-iso2")
    from app.services.webhook_subscription_service import WebhookSubscriptionService

    view = WebhookSubscriptionService().create_subscription(db_session, a1.id, "h", _URL)
    t2 = make_dev_token(o2.id)
    # Чужой аккаунт не виден.
    assert (
        client.get(f"/notification-safety/webhooks/{view['id']}", headers=_h(t2)).status_code == 404
    )
    assert (
        client.post(
            "/notification-safety/webhooks",
            json={"account_id": a1.id, "url": _URL},
            headers=_h(t2),
        ).status_code
        == 404
    )


def test_unsubscribe_public_flow(client: TestClient, db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "sa-unsub")
    token = NotificationUnsubscribeService().issue_unsubscribe_token(
        owner.id, "channel", channel="email"
    )
    # GET страница (публично).
    page = client.get(f"/unsubscribe?token={token}")
    assert page.status_code == 200 and "Отписк" in page.text
    # POST создаёт opt-out (публично).
    done = client.post("/unsubscribe", json={"token": token})
    assert done.status_code == 200 and done.json()["channel"] == "email"
    # Плохой токен → 400.
    assert client.post("/unsubscribe", json={"token": "garbage"}).status_code == 400


def test_no_secrets_in_responses(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "sa-nosec")
    token = make_dev_token(owner.id)
    client.post(
        "/notification-safety/webhooks",
        json={"account_id": account.id, "url": _URL, "signing_secret": _SECRET},
        headers=_h(token),
    )
    body = client.get(
        f"/notification-safety/webhooks?account_id={account.id}", headers=_h(token)
    ).text
    assert _SECRET not in body and _URL not in body
