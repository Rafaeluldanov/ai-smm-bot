"""Тесты REST API AI Execution Coordinator (v0.7.8, offline).

Project/plan/task access (401 без токена); create/list/get/generate/tasks/health; assign/status
(namespaced /execution-tasks); tenant isolation (404); not-approved → 400.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import AIBusinessPlannerService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _seed(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _strategic_plan(db: Session, pid: int, *, approve: bool = True) -> int:
    pl = AIBusinessPlannerService(settings=_SETTINGS)
    gid = pl.create_business_goal(
        db, pid, goal_type="revenue", title="x5", target_value=5000000, current_value=1000000
    )["id"]
    plan = pl.generate_strategic_plan(db, gid)["plan"]
    if approve:
        pl.approve_plan(db, plan["id"])
    return plan["id"]


def _execution(client: TestClient, db: Session, pid: int, uid: int) -> int:
    sp = _strategic_plan(db, pid, approve=True)
    r = client.post(
        f"/projects/{pid}/execution-plans", headers=_h(uid), json={"strategic_plan_id": sp}
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


_ROUTES = [
    ("post", "/projects/1/execution-plans"),
    ("get", "/projects/1/execution-plans"),
    ("get", "/execution-plans/1"),
    ("post", "/execution-plans/1/generate"),
    ("get", "/execution-plans/1/tasks"),
    ("get", "/execution-plans/1/health"),
    ("post", "/execution-tasks/1/assign"),
    ("post", "/execution-tasks/1/status"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_create_and_generate(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi1")
    ep = _execution(client, db_session, pid, uid)
    gen = client.post(f"/execution-plans/{ep}/generate", headers=_h(uid), json={})
    assert gen.status_code == 200
    assert gen.json()["plan"]["status"] == "active"
    assert len(gen.json()["objectives"]) == 4
    tasks = client.get(f"/execution-plans/{ep}/tasks", headers=_h(uid)).json()
    assert len(tasks["tasks"]) == 12


def test_list_and_health(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi2")
    ep = _execution(client, db_session, pid, uid)
    client.post(f"/execution-plans/{ep}/generate", headers=_h(uid), json={})
    lst = client.get(f"/projects/{pid}/execution-plans", headers=_h(uid)).json()
    assert lst["summary"]["plans_total"] == 1
    health = client.get(f"/execution-plans/{ep}/health", headers=_h(uid)).json()
    assert "recommendations" in health and health["tasks_total"] == 12


def test_assign_and_status(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi3")
    ep = _execution(client, db_session, pid, uid)
    client.post(f"/execution-plans/{ep}/generate", headers=_h(uid), json={})
    task_id = client.get(f"/execution-plans/{ep}/tasks", headers=_h(uid)).json()["tasks"][0]["id"]
    a = client.post(
        f"/execution-tasks/{task_id}/assign", headers=_h(uid), json={"owner_user_id": uid}
    )
    assert a.status_code == 200 and a.json()["status"] == "assigned"
    s = client.post(
        f"/execution-tasks/{task_id}/status", headers=_h(uid), json={"status": "completed"}
    )
    assert s.status_code == 200 and s.json()["status"] == "completed"


def test_not_approved_plan_maps_to_400(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi4")
    sp = _strategic_plan(db_session, pid, approve=False)
    r = client.post(
        f"/projects/{pid}/execution-plans", headers=_h(uid), json={"strategic_plan_id": sp}
    )
    assert r.status_code == 400


def test_tenant_isolation(client: TestClient, db_session: Session) -> None:
    pid1, uid1 = _seed(db_session, "exapi5a")
    _pid2, uid2 = _seed(db_session, "exapi5b")
    ep = _execution(client, db_session, pid1, uid1)
    assert client.get(f"/execution-plans/{ep}", headers=_h(uid2)).status_code == 404
    assert (
        client.post(f"/execution-plans/{ep}/generate", headers=_h(uid2), json={}).status_code == 404
    )


def test_missing_plan_maps_to_404(client: TestClient, db_session: Session) -> None:
    _pid, uid = _seed(db_session, "exapi6")
    assert client.get("/execution-plans/999999", headers=_h(uid)).status_code == 404
