"""Тесты REST API AI Decision Engine (v0.7.4, offline).

Project/decision/scenario access (401 без токена); create/analyze/scenarios/select/accept/
apply/explanation; apply требует подтверждения; tenant isolation. Роуты — /ai-decisions
(во избежание коллизии с /decisions Chief of Staff).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate


def _seed(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _mk_decision(client: TestClient, pid: int, uid: int) -> int:
    r = client.post(
        f"/projects/{pid}/ai-decisions",
        headers=_h(uid),
        json={"decision_type": "efficiency", "title": "Низкая конверсия"},
    )
    assert r.status_code == 200
    return r.json()["id"]


_ROUTES = [
    ("post", "/projects/1/ai-decisions"),
    ("get", "/projects/1/ai-decisions"),
    ("get", "/ai-decisions/1"),
    ("post", "/ai-decisions/1/analyze"),
    ("get", "/ai-decisions/1/scenarios"),
    ("get", "/ai-decisions/1/explanation"),
    ("post", "/ai-decisions/1/accept"),
    ("post", "/ai-decisions/1/apply"),
    ("post", "/scenarios/1/select"),
    ("post", "/scenarios/1/reject"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_create_and_list(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "decapi1")
    did = _mk_decision(client, pid, uid)
    assert did > 0
    lst = client.get(f"/projects/{pid}/ai-decisions", headers=_h(uid)).json()["decisions"]
    assert len(lst) == 1


def test_analyze_and_scenarios(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "decapi2")
    did = _mk_decision(client, pid, uid)
    a = client.post(f"/ai-decisions/{did}/analyze", headers=_h(uid), json={})
    assert a.status_code == 200
    assert a.json()["recommendation"]["scenario"] is not None
    sc = client.get(f"/ai-decisions/{did}/scenarios", headers=_h(uid)).json()["scenarios"]
    assert len(sc) == 3


def test_accept_apply_flow(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "decapi3")
    did = _mk_decision(client, pid, uid)
    client.post(f"/ai-decisions/{did}/analyze", headers=_h(uid), json={})
    acc = client.post(f"/ai-decisions/{did}/accept", headers=_h(uid))
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    bad = client.post(f"/ai-decisions/{did}/apply", headers=_h(uid), json={"confirmation": ""})
    assert bad.status_code == 400
    ok = client.post(
        f"/ai-decisions/{did}/apply", headers=_h(uid), json={"confirmation": "APPLY_DECISION"}
    )
    assert ok.status_code == 200 and ok.json()["live_enabled"] is False
    from app.models.post_publication import PostPublication

    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_scenario_select(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "decapi4")
    did = _mk_decision(client, pid, uid)
    scenarios = client.post(f"/ai-decisions/{did}/analyze", headers=_h(uid), json={}).json()[
        "scenarios"
    ]
    sid = scenarios[0]["id"]
    r = client.post(f"/scenarios/{sid}/select", headers=_h(uid))
    assert r.status_code == 200 and r.json()["status"] == "selected"


def test_tenant_isolation_project_and_decision(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "decapi5")
    did = _mk_decision(client, pid, uid)
    other = user_repository.create_user(db_session, email="decapi-o@e.com", password_hash="x")
    db_session.commit()
    assert client.post(
        f"/projects/{pid}/ai-decisions",
        headers=_h(other.id),
        json={"decision_type": "growth", "title": "x"},
    ).status_code in (403, 404)
    assert client.get(f"/ai-decisions/{did}", headers=_h(other.id)).status_code in (403, 404)
    assert client.post(
        f"/ai-decisions/{did}/analyze", headers=_h(other.id), json={}
    ).status_code in (403, 404)


def test_tenant_isolation_scenario(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "decapi6")
    did = _mk_decision(client, pid, uid)
    sid = client.post(f"/ai-decisions/{did}/analyze", headers=_h(uid), json={}).json()["scenarios"][
        0
    ]["id"]
    other = user_repository.create_user(db_session, email="decapi-o2@e.com", password_hash="x")
    db_session.commit()
    assert client.post(f"/scenarios/{sid}/select", headers=_h(other.id)).status_code in (403, 404)
    assert client.post(f"/scenarios/{sid}/reject", headers=_h(other.id)).status_code in (403, 404)
