"""Тесты REST API AI Business Growth Agent (v0.6.9, offline).

Project access; полный проход (analyze/recommendations/accept/reject/apply/explanation);
apply требует подтверждения; tenant isolation (чужой пользователь → 403/404).
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


def _seed_revenue(db: Session, project_id: int) -> None:
    """Пост + событие выручки → growth-анализ находит возможности и создаёт рекомендации."""
    from app.schemas.post import PostCreate
    from app.services.ai_sales_intelligence_service import AISalesIntelligenceService

    post = post_repository.create_post(
        db, PostCreate(project_id=project_id, title="Кейс", status="published", vk_text="x")
    )
    AISalesIntelligenceService().record_lead_event(
        db, project_id, event_type="deal_won", post_id=post.id, platform_key="telegram", value=50000
    )


_ROUTES = [
    ("get", "/projects/1/growth"),
    ("post", "/projects/1/growth/analyze"),
    ("get", "/projects/1/growth/recommendations"),
    ("post", "/projects/1/growth/recommendations/1/accept"),
    ("post", "/projects/1/growth/recommendations/1/reject"),
    ("post", "/projects/1/growth/apply"),
    ("get", "/projects/1/growth/explanation"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_get_growth(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "bga1")
    r = client.get(f"/projects/{pid}/growth", headers=_h(uid))
    assert r.status_code == 200
    assert r.json()["project_id"] == pid


def test_analyze_generates(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "bga2")
    r = client.post(f"/projects/{pid}/growth/analyze", headers=_h(uid))
    assert r.status_code == 200
    body = r.json()
    assert "analysis" in body and "recommendations" in body
    assert "growth_score" in body["analysis"]


def test_review_and_apply_flow(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "bga3")
    _seed_revenue(db_session, pid)
    client.post(f"/projects/{pid}/growth/analyze", headers=_h(uid))
    recs = client.get(f"/projects/{pid}/growth/recommendations", headers=_h(uid)).json()[
        "recommendations"
    ]
    assert recs
    rid = recs[0]["id"]
    a = client.post(f"/projects/{pid}/growth/recommendations/{rid}/accept", headers=_h(uid))
    assert a.status_code == 200 and a.json()["status"] == "accepted"
    bad = client.post(
        f"/projects/{pid}/growth/apply",
        headers=_h(uid),
        json={"recommendation_id": rid, "confirmation": ""},
    )
    assert bad.status_code == 400
    ok = client.post(
        f"/projects/{pid}/growth/apply",
        headers=_h(uid),
        json={"recommendation_id": rid, "confirmation": "APPLY_GROWTH_ACTION"},
    )
    assert ok.status_code == 200
    assert ok.json()["live_enabled"] is False
    # Реальный сигнал: apply не создал ни одной live-публикации.
    from app.models.post_publication import PostPublication

    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_reject_via_api(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "bga4")
    _seed_revenue(db_session, pid)
    client.post(f"/projects/{pid}/growth/analyze", headers=_h(uid))
    recs = client.get(f"/projects/{pid}/growth/recommendations", headers=_h(uid)).json()[
        "recommendations"
    ]
    rid = recs[0]["id"]
    r = client.post(f"/projects/{pid}/growth/recommendations/{rid}/reject", headers=_h(uid))
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_explanation(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "bga5")
    r = client.get(f"/projects/{pid}/growth/explanation", headers=_h(uid))
    assert r.status_code == 200 and "reasons" in r.json()


def test_tenant_isolation_other_user_blocked(client: TestClient, db_session: Session) -> None:
    pid, _uid = _seed(db_session, "bga6")
    other = user_repository.create_user(db_session, email="bga-other@e.com", password_hash="x")
    db_session.commit()
    r = client.get(f"/projects/{pid}/growth", headers=_h(other.id))
    assert r.status_code in (403, 404)
    r2 = client.post(f"/projects/{pid}/growth/analyze", headers=_h(other.id))
    assert r2.status_code in (403, 404)
