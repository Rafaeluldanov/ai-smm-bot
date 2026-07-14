"""Тесты REST API автономного контент-стратега (v0.6.6, offline).

Project access; полный проход (analyze/recommendations/accept/reject/apply/explanation);
apply требует подтверждения; tenant isolation (чужой пользователь → 403/404).
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


_ROUTES = [
    ("get", "/projects/1/strategy"),
    ("post", "/projects/1/strategy/analyze"),
    ("get", "/projects/1/strategy/recommendations"),
    ("post", "/projects/1/strategy/recommendations/1/accept"),
    ("post", "/projects/1/strategy/recommendations/1/reject"),
    ("post", "/projects/1/strategy/apply"),
    ("get", "/projects/1/strategy/explanation"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_get_strategy(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "csa1")
    r = client.get(f"/projects/{pid}/strategy", headers=_h(uid))
    assert r.status_code == 200
    assert r.json()["project_id"] == pid


def test_analyze_generates(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "csa2")
    r = client.post(f"/projects/{pid}/strategy/analyze", headers=_h(uid))
    assert r.status_code == 200
    body = r.json()
    assert "snapshot" in body and "next_month" in body and "generated" in body
    assert len(body["next_month"]["weeks"]) == 4


def test_review_and_apply_flow(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "csa3")
    client.post(f"/projects/{pid}/strategy/analyze", headers=_h(uid))
    recs = client.get(f"/projects/{pid}/strategy/recommendations", headers=_h(uid)).json()[
        "recommendations"
    ]
    assert recs
    rid = recs[0]["id"]
    # accept
    a = client.post(f"/projects/{pid}/strategy/recommendations/{rid}/accept", headers=_h(uid))
    assert a.status_code == 200 and a.json()["status"] == "accepted"
    # apply без подтверждения → 400
    bad = client.post(
        f"/projects/{pid}/strategy/apply",
        headers=_h(uid),
        json={"recommendation_id": rid, "confirmation": ""},
    )
    assert bad.status_code == 400
    # apply с подтверждением → 200, live off
    ok = client.post(
        f"/projects/{pid}/strategy/apply",
        headers=_h(uid),
        json={"recommendation_id": rid, "confirmation": "APPLY_STRATEGY"},
    )
    assert ok.status_code == 200
    assert ok.json()["live_enabled"] is False
    # Реальный сигнал (не только echo-константа): apply не создал ни одной live-публикации.
    from app.models.live_publish_attempt import LivePublishAttempt
    from app.models.post_publication import PostPublication

    assert db_session.query(PostPublication).filter_by(status="published").count() == 0
    assert db_session.query(LivePublishAttempt).filter_by(status="published").count() == 0


def test_reject_via_api(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "csa4")
    client.post(f"/projects/{pid}/strategy/analyze", headers=_h(uid))
    recs = client.get(f"/projects/{pid}/strategy/recommendations", headers=_h(uid)).json()[
        "recommendations"
    ]
    rid = recs[0]["id"]
    r = client.post(f"/projects/{pid}/strategy/recommendations/{rid}/reject", headers=_h(uid))
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_explanation(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "csa5")
    r = client.get(f"/projects/{pid}/strategy/explanation", headers=_h(uid))
    assert r.status_code == 200 and "reasons" in r.json()


def test_tenant_isolation_other_user_blocked(client: TestClient, db_session: Session) -> None:
    pid, _uid = _seed(db_session, "csa6")
    other = user_repository.create_user(db_session, email="csa-other@e.com", password_hash="x")
    db_session.commit()
    r = client.get(f"/projects/{pid}/strategy", headers=_h(other.id))
    assert r.status_code in (403, 404)
