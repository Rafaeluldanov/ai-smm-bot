"""Тесты REST API Autonomous Business OS / AI Executive Layer (v0.7.0, offline).

Project/action access (401 без токена); полный проход (objectives/analyze/plan/actions/
accept/reject/apply/explanation); apply требует подтверждения; tenant isolation.
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
        db, project_id, event_type="deal_won", post_id=post.id, platform_key="telegram", value=50000
    )


_ROUTES = [
    ("post", "/projects/1/objectives"),
    ("get", "/projects/1/objectives"),
    ("post", "/projects/1/executive/analyze"),
    ("get", "/projects/1/executive/plan"),
    ("get", "/projects/1/executive/actions"),
    ("get", "/projects/1/executive/explanation"),
    ("post", "/actions/1/accept"),
    ("post", "/actions/1/reject"),
    ("post", "/actions/1/apply"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_create_and_list_objectives(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi1")
    r = client.post(
        f"/projects/{pid}/objectives",
        headers=_h(uid),
        json={"type": "lead_growth", "title": "Больше лидов"},
    )
    assert r.status_code == 200 and r.json()["status"] == "draft"
    lst = client.get(f"/projects/{pid}/objectives", headers=_h(uid)).json()["objectives"]
    assert len(lst) == 1


def test_analyze_builds_plan(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi2")
    _seed_revenue(db_session, pid)
    r = client.post(f"/projects/{pid}/executive/analyze", headers=_h(uid), json={})
    assert r.status_code == 200
    body = r.json()
    assert body["plan"]["id"] > 0 and body["actions"]


def test_review_and_apply_flow(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi3")
    _seed_revenue(db_session, pid)
    client.post(f"/projects/{pid}/executive/analyze", headers=_h(uid), json={})
    actions = client.get(f"/projects/{pid}/executive/actions", headers=_h(uid)).json()["actions"]
    assert actions
    aid = actions[0]["id"]
    acc = client.post(f"/actions/{aid}/accept", headers=_h(uid))
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    bad = client.post(f"/actions/{aid}/apply", headers=_h(uid), json={"confirmation": ""})
    assert bad.status_code == 400
    ok = client.post(
        f"/actions/{aid}/apply", headers=_h(uid), json={"confirmation": "APPLY_BUSINESS_ACTION"}
    )
    assert ok.status_code == 200 and ok.json()["live_enabled"] is False
    from app.models.post_publication import PostPublication

    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_reject_via_api(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi4")
    _seed_revenue(db_session, pid)
    client.post(f"/projects/{pid}/executive/analyze", headers=_h(uid), json={})
    aid = client.get(f"/projects/{pid}/executive/actions", headers=_h(uid)).json()["actions"][0][
        "id"
    ]
    r = client.post(f"/actions/{aid}/reject", headers=_h(uid))
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_explanation_and_plan(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi5")
    assert "reasons" in client.get(f"/projects/{pid}/executive/explanation", headers=_h(uid)).json()
    plan = client.get(f"/projects/{pid}/executive/plan", headers=_h(uid))
    assert plan.status_code == 200 and plan.json()["project_id"] == pid


def test_tenant_isolation_project_routes(client: TestClient, db_session: Session) -> None:
    pid, _uid = _seed(db_session, "exapi6")
    other = user_repository.create_user(db_session, email="exapi-other@e.com", password_hash="x")
    db_session.commit()
    r = client.post(f"/projects/{pid}/executive/analyze", headers=_h(other.id), json={})
    assert r.status_code in (403, 404)


def test_tenant_isolation_action_routes(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "exapi7")
    _seed_revenue(db_session, pid)
    client.post(f"/projects/{pid}/executive/analyze", headers=_h(uid), json={})
    aid = client.get(f"/projects/{pid}/executive/actions", headers=_h(uid)).json()["actions"][0][
        "id"
    ]
    other = user_repository.create_user(db_session, email="exapi-other2@e.com", password_hash="x")
    db_session.commit()
    # Все три мутирующих роута /actions/{id}/* защищены require_action_access.
    assert client.post(f"/actions/{aid}/accept", headers=_h(other.id)).status_code in (403, 404)
    assert client.post(f"/actions/{aid}/reject", headers=_h(other.id)).status_code in (403, 404)
    assert (
        client.post(
            f"/actions/{aid}/apply",
            headers=_h(other.id),
            json={"confirmation": "APPLY_BUSINESS_ACTION"},
        ).status_code
        in (403, 404)
    )
