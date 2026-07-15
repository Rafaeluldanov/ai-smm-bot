"""Тесты REST API AI Operations Control Center (v0.7.3, offline).

Project/risk/recommendation access (401 без токена); analyze/risks/resolve/recommendations/
accept/reject/history; tenant isolation (чужой пользователь → 403/404).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_workflow_manager_service import AIWorkflowManagerService

_SETTINGS_URL = "https://m.example.com"


def _seed(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _blocked_workflow(db: Session, pid: int) -> None:
    from app.config import Settings

    wf = AIWorkflowManagerService(settings=Settings(media_proxy_public_base_url=_SETTINGS_URL))
    wid = wf.create_workflow_from_goal(db, pid, name="P", workflow_type="sales", status="active")[
        "id"
    ]
    step = wf.generate_workflow_steps(db, wid)[0]["id"]
    wf.create_blocker(db, wid, blocker_type="approval", title="Ждём", step_id=step)


_ROUTES = [
    ("get", "/projects/1/operations"),
    ("post", "/projects/1/operations/analyze"),
    ("get", "/projects/1/operations/risks"),
    ("get", "/projects/1/operations/recommendations"),
    ("get", "/projects/1/operations/history"),
    ("get", "/projects/1/operations/explanation"),
    ("post", "/risks/1/resolve"),
    ("post", "/recommendations/1/accept"),
    ("post", "/recommendations/1/reject"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_analyze_and_get(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "opsapi1")
    r = client.post(f"/projects/{pid}/operations/analyze", headers=_h(uid), json={})
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["snapshot"]["health_score"] <= 100
    got = client.get(f"/projects/{pid}/operations", headers=_h(uid))
    assert got.status_code == 200 and got.json()["has_snapshot"] is True


def test_risks_and_resolve(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "opsapi2")
    _blocked_workflow(db_session, pid)
    client.post(f"/projects/{pid}/operations/analyze", headers=_h(uid), json={})
    risks = client.get(f"/projects/{pid}/operations/risks", headers=_h(uid)).json()["risks"]
    assert risks
    rid = risks[0]["id"]
    r = client.post(f"/risks/{rid}/resolve", headers=_h(uid))
    assert r.status_code == 200 and r.json()["status"] == "resolved"


def test_recommendations_accept_reject(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "opsapi3")
    _blocked_workflow(db_session, pid)
    client.post(f"/projects/{pid}/operations/analyze", headers=_h(uid), json={})
    recs = client.get(f"/projects/{pid}/operations/recommendations", headers=_h(uid)).json()[
        "recommendations"
    ]
    assert recs
    a = client.post(f"/recommendations/{recs[0]['id']}/accept", headers=_h(uid))
    assert a.status_code == 200 and a.json()["status"] == "accepted"
    from app.models.post_publication import PostPublication

    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_history(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "opsapi4")
    client.post(f"/projects/{pid}/operations/analyze", headers=_h(uid), json={})
    h = client.get(f"/projects/{pid}/operations/history", headers=_h(uid))
    assert h.status_code == 200 and len(h.json()["history"]) == 1


def test_explanation(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "opsapi7")
    client.post(f"/projects/{pid}/operations/analyze", headers=_h(uid), json={})
    r = client.get(f"/projects/{pid}/operations/explanation", headers=_h(uid))
    assert r.status_code == 200 and r.json()["reasons"]


def test_tenant_isolation_project_routes(client: TestClient, db_session: Session) -> None:
    pid, _uid = _seed(db_session, "opsapi5")
    other = user_repository.create_user(db_session, email="opsapi-o@e.com", password_hash="x")
    db_session.commit()
    r = client.post(f"/projects/{pid}/operations/analyze", headers=_h(other.id), json={})
    assert r.status_code in (403, 404)


def test_tenant_isolation_risk_and_recommendation(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "opsapi6")
    _blocked_workflow(db_session, pid)
    client.post(f"/projects/{pid}/operations/analyze", headers=_h(uid), json={})
    rid = client.get(f"/projects/{pid}/operations/risks", headers=_h(uid)).json()["risks"][0]["id"]
    recs = client.get(f"/projects/{pid}/operations/recommendations", headers=_h(uid)).json()[
        "recommendations"
    ]
    other = user_repository.create_user(db_session, email="opsapi-o2@e.com", password_hash="x")
    db_session.commit()
    assert client.post(f"/risks/{rid}/resolve", headers=_h(other.id)).status_code in (403, 404)
    if recs:
        assert client.post(
            f"/recommendations/{recs[0]['id']}/accept", headers=_h(other.id)
        ).status_code in (403, 404)
