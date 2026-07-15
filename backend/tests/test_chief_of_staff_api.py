"""Тесты REST API AI Chief of Staff (v0.7.1, offline).

Project/task/decision access (401 без токена); briefing/weekly; tasks accept/reject/complete;
decisions save/list/disable; tenant isolation (чужой пользователь → 403/404).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.ai_sales_intelligence_service import AISalesIntelligenceService


def _seed(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _seed_revenue(db: Session, project_id: int) -> None:
    post = post_repository.create_post(
        db, PostCreate(project_id=project_id, title="Кейс", status="published", vk_text="x")
    )
    AISalesIntelligenceService().record_lead_event(
        db, project_id, event_type="deal_won", post_id=post.id, platform_key="telegram", value=70000
    )


_ROUTES = [
    ("get", "/projects/1/briefing"),
    ("post", "/projects/1/briefing/generate"),
    ("post", "/projects/1/briefing/weekly"),
    ("get", "/projects/1/tasks"),
    ("post", "/tasks/1/accept"),
    ("post", "/tasks/1/reject"),
    ("post", "/tasks/1/complete"),
    ("post", "/projects/1/decisions"),
    ("get", "/projects/1/decisions"),
    ("delete", "/decisions/1"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method in ("get", "delete") else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_generate_briefing(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "chapi1")
    _seed_revenue(db_session, pid)
    r = client.post(f"/projects/{pid}/briefing/generate", headers=_h(uid), json={})
    assert r.status_code == 200
    body = r.json()
    assert body["briefing"]["type"] == "daily" and body["tasks"]


def test_weekly_and_get_briefing(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "chapi2")
    _seed_revenue(db_session, pid)
    w = client.post(f"/projects/{pid}/briefing/weekly", headers=_h(uid), json={})
    assert w.status_code == 200 and w.json()["briefing"]["type"] == "weekly"
    g = client.get(f"/projects/{pid}/briefing", headers=_h(uid))
    assert g.status_code == 200 and g.json()["has_briefing"] is True


def test_task_accept_complete_flow(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "chapi3")
    _seed_revenue(db_session, pid)
    client.post(f"/projects/{pid}/briefing/generate", headers=_h(uid), json={})
    tasks = client.get(f"/projects/{pid}/tasks", headers=_h(uid)).json()["tasks"]
    assert tasks
    tid = tasks[0]["id"]
    acc = client.post(f"/tasks/{tid}/accept", headers=_h(uid))
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    comp = client.post(f"/tasks/{tid}/complete", headers=_h(uid))
    assert comp.status_code == 200 and comp.json()["status"] == "completed"
    from app.models.post_publication import PostPublication

    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_decisions_crud(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "chapi4")
    r = client.post(
        f"/projects/{pid}/decisions",
        headers=_h(uid),
        json={"decision_type": "restriction", "key": "sales_style", "value": {"style": "soft"}},
    )
    assert r.status_code == 200 and r.json()["active"] is True
    did = r.json()["id"]
    lst = client.get(f"/projects/{pid}/decisions", headers=_h(uid)).json()["decisions"]
    assert len(lst) == 1
    d = client.delete(f"/decisions/{did}", headers=_h(uid))
    assert d.status_code == 200 and d.json()["active"] is False
    assert client.get(f"/projects/{pid}/decisions", headers=_h(uid)).json()["decisions"] == []


def test_tenant_isolation_project_routes(client: TestClient, db_session: Session) -> None:
    pid, _uid = _seed(db_session, "chapi5")
    other = user_repository.create_user(db_session, email="chapi-o@e.com", password_hash="x")
    db_session.commit()
    r = client.post(f"/projects/{pid}/briefing/generate", headers=_h(other.id), json={})
    assert r.status_code in (403, 404)


def test_tenant_isolation_task_and_decision_routes(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "chapi6")
    _seed_revenue(db_session, pid)
    client.post(f"/projects/{pid}/briefing/generate", headers=_h(uid), json={})
    tid = client.get(f"/projects/{pid}/tasks", headers=_h(uid)).json()["tasks"][0]["id"]
    did = client.post(
        f"/projects/{pid}/decisions",
        headers=_h(uid),
        json={"decision_type": "preference", "key": "k", "value": {}},
    ).json()["id"]
    other = user_repository.create_user(db_session, email="chapi-o2@e.com", password_hash="x")
    db_session.commit()
    # Все мутирующие роуты /tasks/{id}/* и /decisions/{id} защищены от чужого пользователя.
    assert client.post(f"/tasks/{tid}/accept", headers=_h(other.id)).status_code in (403, 404)
    assert client.post(f"/tasks/{tid}/reject", headers=_h(other.id)).status_code in (403, 404)
    assert client.post(f"/tasks/{tid}/complete", headers=_h(other.id)).status_code in (403, 404)
    assert client.delete(f"/decisions/{did}", headers=_h(other.id)).status_code in (403, 404)
