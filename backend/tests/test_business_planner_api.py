"""Тесты REST API AI Business Planner (v0.7.7, offline).

Project/goal/plan access (401 без токена); create/list/get(gap)/plan; plan/objectives/approve/
convert; convert требует подтверждения; tenant isolation (404 на чужое); missing → 404.
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


def _goal(client: TestClient, pid: int, uid: int) -> int:
    r = client.post(
        f"/projects/{pid}/goals",
        headers=_h(uid),
        json={
            "goal_type": "revenue",
            "title": "Выручка",
            "target_value": 5000000,
            "current_value": 1000000,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _plan(client: TestClient, goal_id: int, uid: int) -> int:
    r = client.post(f"/goals/{goal_id}/plan", headers=_h(uid), json={})
    assert r.status_code == 200, r.text
    return r.json()["plan"]["id"]


_ROUTES = [
    ("post", "/projects/1/goals"),
    ("get", "/projects/1/goals"),
    ("get", "/goals/1"),
    ("post", "/goals/1/plan"),
    ("get", "/plans/1"),
    ("get", "/plans/1/objectives"),
    ("post", "/plans/1/approve"),
    ("post", "/plans/1/convert-workflow"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_create_goal_and_list(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "plapi1")
    gid = _goal(client, pid, uid)
    assert gid > 0
    lst = client.get(f"/projects/{pid}/goals", headers=_h(uid)).json()
    assert len(lst["goals"]) == 1 and lst["summary"]["goals_total"] == 1


def test_get_goal_returns_gap(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "plapi2")
    gid = _goal(client, pid, uid)
    got = client.get(f"/goals/{gid}", headers=_h(uid)).json()
    assert got["gap"]["gap"] == 4000000.0


def test_generate_plan_and_objectives(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "plapi3")
    gid = _goal(client, pid, uid)
    plan_id = _plan(client, gid, uid)
    p = client.get(f"/plans/{plan_id}", headers=_h(uid)).json()
    assert len(p["objectives"]) == 4
    assert p["explanation"]["reasons"]
    objs = client.get(f"/plans/{plan_id}/objectives", headers=_h(uid)).json()
    assert len(objs["objectives"]) == 4


def test_approve_and_convert(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "plapi4")
    gid = _goal(client, pid, uid)
    plan_id = _plan(client, gid, uid)
    # convert без approve → 400
    bad = client.post(
        f"/plans/{plan_id}/convert-workflow", headers=_h(uid), json={"confirmation": "CONVERT_PLAN"}
    )
    assert bad.status_code == 400
    assert client.post(f"/plans/{plan_id}/approve", headers=_h(uid), json={}).status_code == 200
    # convert без подтверждения → 400
    assert (
        client.post(f"/plans/{plan_id}/convert-workflow", headers=_h(uid), json={}).status_code
        == 400
    )
    ok = client.post(
        f"/plans/{plan_id}/convert-workflow", headers=_h(uid), json={"confirmation": "CONVERT_PLAN"}
    )
    assert ok.status_code == 200 and ok.json()["live_enabled"] is False


def test_tenant_isolation_blocks_foreign(client: TestClient, db_session: Session) -> None:
    pid1, uid1 = _seed(db_session, "plapi5a")
    _pid2, uid2 = _seed(db_session, "plapi5b")
    gid = _goal(client, pid1, uid1)
    plan_id = _plan(client, gid, uid1)
    assert client.get(f"/goals/{gid}", headers=_h(uid2)).status_code == 404
    assert client.get(f"/plans/{plan_id}", headers=_h(uid2)).status_code == 404
    assert client.post(f"/plans/{plan_id}/approve", headers=_h(uid2), json={}).status_code == 404


def test_unknown_goal_type_maps_to_400(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "plapi6")
    r = client.post(
        f"/projects/{pid}/goals", headers=_h(uid), json={"goal_type": "bogus", "title": "x"}
    )
    assert r.status_code == 400


def test_missing_goal_maps_to_404(client: TestClient, db_session: Session) -> None:
    _pid, uid = _seed(db_session, "plapi7")
    assert client.get("/goals/999999", headers=_h(uid)).status_code == 404
