"""Тесты REST API AI Campaign Manager (v0.6.7, offline).

Tenant-гард; полный проход (create/generate/strategy/recs/accept/approve/apply/preview);
apply требует approve + подтверждения; tenant isolation (чужой пользователь → 401/403/404).
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


def _create(client: TestClient, pid: int, uid: int, goal: str = "sales") -> int:
    r = client.post(
        f"/projects/{pid}/campaigns",
        headers=_h(uid),
        json={"name": "Кампания", "goal": goal, "product_context": {"name": "Худи"}},
    )
    assert r.status_code == 200
    return r.json()["id"]


_ROUTES = [
    ("post", "/projects/1/campaigns"),
    ("get", "/projects/1/campaigns"),
    ("get", "/campaigns/1"),
    ("post", "/campaigns/1/generate"),
    ("get", "/campaigns/1/strategy"),
    ("get", "/campaigns/1/explanation"),
    ("get", "/campaigns/1/recommendations"),
    ("post", "/campaigns/1/recommendations/1/accept"),
    ("post", "/campaigns/1/recommendations/1/reject"),
    ("post", "/campaigns/1/approve"),
    ("post", "/campaigns/1/apply"),
    ("get", "/campaigns/1/calendar-preview"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_create_and_list(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "capi1")
    cid = _create(client, pid, uid)
    r = client.get(f"/projects/{pid}/campaigns", headers=_h(uid))
    assert r.status_code == 200
    assert any(c["id"] == cid for c in r.json()["campaigns"])


def test_generate_plan(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "capi2")
    cid = _create(client, pid, uid)
    r = client.post(f"/campaigns/{cid}/generate", headers=_h(uid))
    assert r.status_code == 200
    body = r.json()
    assert "strategy" in body and "stages" in body and "recommendations" in body
    assert body["stages"]


def test_review_approve_apply_flow(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "capi3")
    cid = _create(client, pid, uid)
    client.post(f"/campaigns/{cid}/generate", headers=_h(uid))
    recs = client.get(f"/campaigns/{cid}/recommendations", headers=_h(uid)).json()[
        "recommendations"
    ]
    rid = recs[0]["id"]
    acc = client.post(f"/campaigns/{cid}/recommendations/{rid}/accept", headers=_h(uid))
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    # apply до approve → 400
    bad = client.post(
        f"/campaigns/{cid}/apply", headers=_h(uid), json={"confirmation": "APPLY_CAMPAIGN"}
    )
    assert bad.status_code == 400
    # approve
    ap = client.post(f"/campaigns/{cid}/approve", headers=_h(uid))
    assert ap.status_code == 200 and ap.json()["status"] == "approved"
    # apply без подтверждения → 400
    bad2 = client.post(f"/campaigns/{cid}/apply", headers=_h(uid), json={"confirmation": ""})
    assert bad2.status_code == 400
    # apply с подтверждением → 200, live off
    ok = client.post(
        f"/campaigns/{cid}/apply", headers=_h(uid), json={"confirmation": "APPLY_CAMPAIGN"}
    )
    assert ok.status_code == 200
    assert ok.json()["live_enabled"] is False
    # Реальные сигналы (не только echo-константа): только черновик, активный календарь не тронут.
    from app.models.autopilot_calendar_plan import AutopilotCalendarPlan
    from app.models.crm_bot_smm import CrmPublishingPlan
    from app.models.post_publication import PostPublication

    plans = db_session.query(AutopilotCalendarPlan).filter_by(project_id=pid).all()
    assert plans and all(p.status == "draft" for p in plans)
    assert db_session.query(CrmPublishingPlan).filter_by(project_id=pid).count() == 0
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_calendar_preview(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "capi4")
    cid = _create(client, pid, uid)
    client.post(f"/campaigns/{cid}/generate", headers=_h(uid))
    r = client.get(f"/campaigns/{cid}/calendar-preview", headers=_h(uid))
    assert r.status_code == 200
    assert len(r.json()["weeks"]) == 4


def test_tenant_isolation_other_user_blocked(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "capi5")
    cid = _create(client, pid, uid)
    other = user_repository.create_user(db_session, email="capi-other@e.com", password_hash="x")
    db_session.commit()
    r = client.get(f"/campaigns/{cid}", headers=_h(other.id))
    assert r.status_code in (403, 404)


def test_tenant_isolation_mutating_routes_blocked(client: TestClient, db_session: Session) -> None:
    """Чужой (авторизованный) пользователь не может менять кампанию (guard, не 401)."""
    pid, uid = _seed(db_session, "capi6")
    cid = _create(client, pid, uid)
    client.post(f"/campaigns/{cid}/generate", headers=_h(uid))
    other = user_repository.create_user(db_session, email="capi-other2@e.com", password_hash="x")
    db_session.commit()
    h = _h(other.id)
    # Мутирующие роуты под require_campaign_access → 403/404 для чужого аккаунта.
    assert client.post(f"/campaigns/{cid}/generate", headers=h).status_code in (403, 404)
    assert client.post(f"/campaigns/{cid}/approve", headers=h).status_code in (403, 404)
    assert client.post(
        f"/campaigns/{cid}/apply", headers=h, json={"confirmation": "APPLY_CAMPAIGN"}
    ).status_code in (403, 404)
    # Project-scoped create тоже закрыт для чужого проекта.
    assert client.post(
        f"/projects/{pid}/campaigns", headers=h, json={"name": "X", "goal": "sales"}
    ).status_code in (403, 404)
