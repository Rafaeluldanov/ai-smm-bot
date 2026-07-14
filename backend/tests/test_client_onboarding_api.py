"""Тесты REST API клиентского онбординга (v0.6.4, offline).

Auth required; полный проход 5 шагов; live не включается; tenant isolation.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import user_repository


def _uid(db: Session, email: str) -> int:
    return user_repository.create_user(db, email=email, password_hash="x").id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


# Все 7 маршрутов онбординга должны требовать авторизацию (401 без токена).
_ROUTES = [
    ("post", "/onboarding/start"),
    ("get", "/onboarding/1"),
    ("post", "/onboarding/1/business"),
    ("post", "/onboarding/1/media"),
    ("post", "/onboarding/1/platforms"),
    ("post", "/onboarding/1/goal"),
    ("post", "/onboarding/1/finish"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 401


def test_start_and_get(client: TestClient, db_session: Session) -> None:
    uid = _uid(db_session, "oba1@e.com")
    r = client.post("/onboarding/start", headers=_h(uid), json={"company_name": "TEEON"})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    g = client.get(f"/onboarding/{sid}", headers=_h(uid))
    assert g.status_code == 200 and g.json()["current_step"] == 1


def test_full_flow_ready_live_off(client: TestClient, db_session: Session) -> None:
    uid = _uid(db_session, "oba-full@e.com")
    sid = client.post("/onboarding/start", headers=_h(uid), json={"company_name": "T"}).json()[
        "session_id"
    ]
    assert (
        client.post(
            f"/onboarding/{sid}/business", headers=_h(uid), json={"company_name": "T"}
        ).status_code
        == 200
    )
    client.post(
        f"/onboarding/{sid}/media",
        headers=_h(uid),
        json={"yandex_disk_url": "https://disk.yandex.ru/d/x"},
    )
    client.post(f"/onboarding/{sid}/platforms", headers=_h(uid), json={"telegram": True})
    client.post(
        f"/onboarding/{sid}/goal", headers=_h(uid), json={"goal": "sales", "frequency": "3_week"}
    )
    fin = client.post(f"/onboarding/{sid}/finish", headers=_h(uid))
    assert fin.status_code == 200
    body = fin.json()
    assert body["status"] == "ready"
    assert body["live_enabled"] is False
    # Реальный сигнал (не только echo хардкод-константы): live-отправок не было.
    from app.models.live_publish_attempt import LivePublishAttempt

    assert db_session.query(LivePublishAttempt).filter_by(status="published").count() == 0


def test_finish_blocked_when_incomplete(client: TestClient, db_session: Session) -> None:
    uid = _uid(db_session, "oba-inc@e.com")
    sid = client.post("/onboarding/start", headers=_h(uid), json={}).json()["session_id"]
    r = client.post(f"/onboarding/{sid}/finish", headers=_h(uid))
    assert r.status_code == 400


def test_tenant_isolation(client: TestClient, db_session: Session) -> None:
    uid_a = _uid(db_session, "oba-a@e.com")
    uid_b = _uid(db_session, "oba-b@e.com")
    sid = client.post("/onboarding/start", headers=_h(uid_a), json={"company_name": "A"}).json()[
        "session_id"
    ]
    # Пользователь B не видит сессию A.
    assert client.get(f"/onboarding/{sid}", headers=_h(uid_b)).status_code == 404
