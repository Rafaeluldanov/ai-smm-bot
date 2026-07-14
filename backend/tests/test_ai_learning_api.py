"""Тесты REST API AI Learning Loop (v0.6.5, offline).

Project access; полный проход (summary/analyze/recommendations/explanation/feedback/reset);
обучение НЕ включает live и НЕ публикует; tenant isolation (чужой проект → 403/404).
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
    ("get", "/projects/1/learning"),
    ("post", "/projects/1/learning/analyze"),
    ("get", "/projects/1/learning/recommendations"),
    ("get", "/projects/1/learning/explanation"),
    ("post", "/projects/1/learning/feedback"),
    ("post", "/projects/1/learning/reset"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_get_learning(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "apil1")
    r = client.get(f"/projects/{pid}/learning", headers=_h(uid))
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == pid
    assert body["status"] == "learning"


def test_analyze_and_recommendations(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "apil2")
    a = client.post(f"/projects/{pid}/learning/analyze", headers=_h(uid), json={"window_days": 60})
    assert a.status_code == 200
    r = client.get(f"/projects/{pid}/learning/recommendations", headers=_h(uid))
    assert r.status_code == 200
    body = r.json()
    assert "next_content" in body and "strategy" in body
    # Стратегия — только рекомендация (никогда не применяется автоматически).
    assert "не применяет" in body["strategy"]["note"]


def test_feedback(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "apil3")
    r = client.post(
        f"/projects/{pid}/learning/feedback", headers=_h(uid), json={"sentiment": "good"}
    )
    assert r.status_code == 200
    assert r.json()["event_type"] == "client_rating"


def test_feedback_bad_input_400(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "apil4")
    r = client.post(f"/projects/{pid}/learning/feedback", headers=_h(uid), json={})
    assert r.status_code == 400


def test_reset(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "apil5")
    r = client.post(f"/projects/{pid}/learning/reset", headers=_h(uid))
    assert r.status_code == 200
    assert r.json()["learning_score"] == 0.0


def test_explanation(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "apil6")
    r = client.get(f"/projects/{pid}/learning/explanation", headers=_h(uid))
    assert r.status_code == 200
    assert "understood" in r.json()


def test_tenant_isolation_other_user_blocked(client: TestClient, db_session: Session) -> None:
    pid, _uid = _seed(db_session, "apil7")
    other = user_repository.create_user(db_session, email="apil-other@e.com", password_hash="x")
    db_session.commit()
    r = client.get(f"/projects/{pid}/learning", headers=_h(other.id))
    assert r.status_code in (403, 404)
