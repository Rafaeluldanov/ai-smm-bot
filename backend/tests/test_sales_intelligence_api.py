"""Тесты REST API AI Sales & Lead Intelligence (v0.6.8, offline).

Project access; полный проход (leads/analyze/get/revenue/explanation/reset);
tenant isolation (чужой пользователь → 403/404); live не включается.
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
    ("get", "/projects/1/sales-intelligence"),
    ("post", "/projects/1/sales-intelligence/analyze"),
    ("post", "/projects/1/sales-intelligence/leads"),
    ("get", "/projects/1/sales-intelligence/revenue"),
    ("get", "/projects/1/sales-intelligence/explanation"),
    ("post", "/projects/1/sales-intelligence/reset"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_get_intelligence(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "sapi1")
    r = client.get(f"/projects/{pid}/sales-intelligence", headers=_h(uid))
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == pid
    assert "revenue_summary" in body and "recommendations" in body


def test_lead_analyze_revenue_flow(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "sapi2")
    # Регистрируем выручку по посту.
    lead = client.post(
        f"/projects/{pid}/sales-intelligence/leads",
        headers=_h(uid),
        json={
            "event_type": "deal_won",
            "source_type": "post",
            "value": 40000,
            "platform_key": "telegram",
        },
    )
    assert lead.status_code == 200
    # Анализ.
    an = client.post(f"/projects/{pid}/sales-intelligence/analyze", headers=_h(uid))
    assert an.status_code == 200
    assert an.json()["status"] == "active"
    # Отчёт по выручке.
    rev = client.get(f"/projects/{pid}/sales-intelligence/revenue", headers=_h(uid))
    assert rev.status_code == 200
    assert rev.json()["analysis"]["total_revenue"] == 40000.0


def test_lead_bad_event_400(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "sapi3")
    r = client.post(
        f"/projects/{pid}/sales-intelligence/leads", headers=_h(uid), json={"event_type": "nope"}
    )
    assert r.status_code == 400


def test_explanation(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "sapi4")
    r = client.get(f"/projects/{pid}/sales-intelligence/explanation", headers=_h(uid))
    assert r.status_code == 200
    assert "reasons" in r.json()


def test_reset(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "sapi5")
    r = client.post(f"/projects/{pid}/sales-intelligence/reset", headers=_h(uid))
    assert r.status_code == 200
    assert r.json()["status"] == "learning"


def test_tenant_isolation_other_user_blocked(client: TestClient, db_session: Session) -> None:
    pid, _uid = _seed(db_session, "sapi6")
    other = user_repository.create_user(db_session, email="sapi-other@e.com", password_hash="x")
    db_session.commit()
    r = client.get(f"/projects/{pid}/sales-intelligence", headers=_h(other.id))
    assert r.status_code in (403, 404)
    r2 = client.post(
        f"/projects/{pid}/sales-intelligence/leads",
        headers=_h(other.id),
        json={"event_type": "deal_won", "value": 999},
    )
    assert r2.status_code in (403, 404)
