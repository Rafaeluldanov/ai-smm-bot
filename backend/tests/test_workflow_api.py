"""Тесты REST API AI Workflow Manager (v0.7.2, offline).

Project/workflow/step/blocker access (401 без токена); create/generate/assign/status/blocker/
resolve/health; tenant isolation (чужой пользователь → 403/404).
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


def _mk_workflow(client: TestClient, pid: int, uid: int) -> int:
    r = client.post(
        f"/projects/{pid}/workflows",
        headers=_h(uid),
        json={"name": "Рост", "workflow_type": "sales", "goal": "sales", "status": "active"},
    )
    assert r.status_code == 200
    return r.json()["id"]


def _gen_steps(client: TestClient, wid: int, uid: int) -> list:
    r = client.post(f"/workflows/{wid}/generate-steps", headers=_h(uid), json={})
    assert r.status_code == 200
    return r.json()["steps"]


_ROUTES = [
    ("post", "/projects/1/workflows"),
    ("get", "/projects/1/workflows"),
    ("get", "/workflows/1"),
    ("post", "/workflows/1/generate-steps"),
    ("get", "/workflows/1/steps"),
    ("get", "/workflows/1/health"),
    ("post", "/workflows/1/blockers"),
    ("post", "/steps/1/assign"),
    ("post", "/steps/1/status"),
    ("post", "/blockers/1/resolve"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_create_and_list_workflows(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "wfapi1")
    wid = _mk_workflow(client, pid, uid)
    assert wid > 0
    lst = client.get(f"/projects/{pid}/workflows", headers=_h(uid)).json()["workflows"]
    assert len(lst) == 1


def test_generate_steps_and_get(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "wfapi2")
    wid = _mk_workflow(client, pid, uid)
    steps = _gen_steps(client, wid, uid)
    assert len(steps) == 3
    bundle = client.get(f"/workflows/{wid}", headers=_h(uid)).json()
    assert bundle["workflow"]["id"] == wid and len(bundle["steps"]) == 3


def test_assign_status_complete_flow(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "wfapi3")
    wid = _mk_workflow(client, pid, uid)
    steps = _gen_steps(client, wid, uid)
    sid = steps[0]["id"]
    a = client.post(f"/steps/{sid}/assign", headers=_h(uid), json={"owner_user_id": uid})
    assert a.status_code == 200 and a.json()["status"] == "assigned"
    c = client.post(f"/steps/{sid}/status", headers=_h(uid), json={"status": "completed"})
    assert c.status_code == 200 and c.json()["status"] == "completed"
    from app.models.post_publication import PostPublication

    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_blocker_and_health(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "wfapi4")
    wid = _mk_workflow(client, pid, uid)
    steps = _gen_steps(client, wid, uid)
    b = client.post(
        f"/workflows/{wid}/blockers",
        headers=_h(uid),
        json={"blocker_type": "approval", "title": "Ждём", "step_id": steps[0]["id"]},
    )
    assert b.status_code == 200
    bid = b.json()["id"]
    health = client.get(f"/workflows/{wid}/health", headers=_h(uid))
    assert health.status_code == 200 and health.json()["open_blockers"] == 1
    r = client.post(f"/blockers/{bid}/resolve", headers=_h(uid))
    assert r.status_code == 200 and r.json()["status"] == "resolved"


def test_tenant_isolation_project_and_workflow(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "wfapi5")
    wid = _mk_workflow(client, pid, uid)
    other = user_repository.create_user(db_session, email="wfapi-o@e.com", password_hash="x")
    db_session.commit()
    assert client.post(
        f"/projects/{pid}/workflows",
        headers=_h(other.id),
        json={"name": "x", "workflow_type": "sales"},
    ).status_code in (403, 404)
    assert client.get(f"/workflows/{wid}", headers=_h(other.id)).status_code in (403, 404)
    assert client.post(
        f"/workflows/{wid}/generate-steps", headers=_h(other.id), json={}
    ).status_code in (403, 404)


def test_tenant_isolation_step_and_blocker(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "wfapi6")
    wid = _mk_workflow(client, pid, uid)
    sid = _gen_steps(client, wid, uid)[0]["id"]
    bid = client.post(
        f"/workflows/{wid}/blockers",
        headers=_h(uid),
        json={"blocker_type": "resource", "title": "b"},
    ).json()["id"]
    other = user_repository.create_user(db_session, email="wfapi-o2@e.com", password_hash="x")
    db_session.commit()
    assert client.post(
        f"/steps/{sid}/status", headers=_h(other.id), json={"status": "completed"}
    ).status_code in (403, 404)
    assert client.post(
        f"/steps/{sid}/assign", headers=_h(other.id), json={"owner_user_id": other.id}
    ).status_code in (403, 404)
    assert client.post(f"/blockers/{bid}/resolve", headers=_h(other.id)).status_code in (403, 404)
