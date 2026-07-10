"""HTTP-тесты сессионного auth API: login/refresh/logout/logout-all/sessions + аудит."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLogEntry


def _register(client: TestClient, email: str = "sess@example.com") -> dict:
    return client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "account_name": "WS"},
    ).json()


def test_login_returns_access_and_sets_refresh_cookie(client: TestClient) -> None:
    body = _register(client)
    assert body["access_token"] and body["token"] == body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    login = client.post(
        "/auth/login", json={"email": "sess@example.com", "password": "password123"}
    )
    assert login.status_code == 200
    assert "botfleet_refresh" in login.cookies


def test_sessions_list_has_no_token_hash(client: TestClient) -> None:
    body = _register(client)
    h = {"Authorization": body["access_token"]}
    sessions = client.get("/auth/sessions", headers=h).json()
    assert len(sessions) >= 1
    for s in sessions:
        joined = " ".join(str(k) for k in s)
        assert "refresh_token_hash" not in joined
        assert "hash" not in joined


def test_refresh_rotates_and_new_access_works(client: TestClient) -> None:
    _register(client)  # sets refresh cookie on the client
    r1 = client.post("/auth/refresh")
    assert r1.status_code == 200
    new_access = r1.json()["access_token"]
    assert new_access
    # Новый access-токен принимается.
    me = client.get("/auth/me", headers={"Authorization": new_access})
    assert me.status_code == 200


def test_logout_revokes_current_session(client: TestClient) -> None:
    body = _register(client)
    h = {"Authorization": body["access_token"]}
    assert len(client.get("/auth/sessions", headers=h).json()) == 1
    out = client.post("/auth/logout", headers=h)
    assert out.status_code == 200 and out.json()["revoked_sessions"] == 1
    assert client.get("/auth/sessions", headers=h).json() == []


def test_logout_all_revokes_every_session(client: TestClient) -> None:
    _register(client, "many@example.com")
    # Ещё один вход (вторая сессия).
    body = client.post(
        "/auth/login", json={"email": "many@example.com", "password": "password123"}
    ).json()
    h = {"Authorization": body["access_token"]}
    assert len(client.get("/auth/sessions", headers=h).json()) == 2
    out = client.post("/auth/logout-all", headers=h)
    assert out.status_code == 200 and out.json()["revoked_sessions"] == 2
    assert client.get("/auth/sessions", headers=h).json() == []


def test_refresh_after_logout_rejected(client: TestClient) -> None:
    body = _register(client, "gone@example.com")
    client.post("/auth/logout", headers={"Authorization": body["access_token"]})
    # refresh-cookie ещё есть у клиента, но сессия отозвана → 401.
    assert client.post("/auth/refresh").status_code == 401


def test_audit_events_recorded(client: TestClient, db_session: Session) -> None:
    _register(client, "audit@example.com")
    client.post("/auth/login", json={"email": "audit@example.com", "password": "password123"})
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "user.registered" in actions
    assert "user.login" in actions
