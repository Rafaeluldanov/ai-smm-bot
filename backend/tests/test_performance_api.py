"""Тесты REST API AI Performance Intelligence (v0.7.9, offline).

Project/snapshot access (401 без токена); analyze/list/get/metrics/deviations/recommendations;
tenant isolation (404 на чужое); missing → 404.
"""

from types import SimpleNamespace

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


def _below(db: Session, pid: int, monkeypatch: pytest.MonkeyPatch) -> None:
    AIBusinessPlannerService(settings=_SETTINGS).create_business_goal(
        db, pid, goal_type="revenue", title="rev", target_value=1000000, current_value=100000
    )
    monkeypatch.setattr(
        "app.repositories.business_growth_repository.get_profile",
        lambda *_a, **_k: SimpleNamespace(
            current_state={"total_revenue": 700000.0, "conversion_rate": 0.1, "leads": 50},
            growth_score=40.0,
        ),
    )


_ROUTES = [
    ("post", "/projects/1/performance/analyze"),
    ("get", "/projects/1/performance"),
    ("get", "/performance/1"),
    ("get", "/performance/1/metrics"),
    ("get", "/performance/1/deviations"),
    ("get", "/performance/1/recommendations"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_analyze_and_get(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, uid = _seed(db_session, "pfapi1")
    _below(db_session, pid, monkeypatch)
    a = client.post(f"/projects/{pid}/performance/analyze", headers=_h(uid), json={})
    assert a.status_code == 200
    sid = a.json()["snapshot"]["id"]
    assert a.json()["metrics"] and a.json()["recommendations"]
    got = client.get(f"/performance/{sid}", headers=_h(uid))
    assert got.status_code == 200 and got.json()["explanation"]["reasons"]


def test_list_and_subresources(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, uid = _seed(db_session, "pfapi2")
    _below(db_session, pid, monkeypatch)
    sid = client.post(f"/projects/{pid}/performance/analyze", headers=_h(uid), json={}).json()[
        "snapshot"
    ]["id"]
    lst = client.get(f"/projects/{pid}/performance", headers=_h(uid)).json()
    assert lst["summary"]["snapshots_total"] == 1
    m = client.get(f"/performance/{sid}/metrics", headers=_h(uid)).json()
    assert m["metrics"]
    d = client.get(f"/performance/{sid}/deviations", headers=_h(uid)).json()
    assert "deviations" in d
    r = client.get(f"/performance/{sid}/recommendations", headers=_h(uid)).json()
    assert r["recommendations"] and r["explanation"]["reasons"]


def test_tenant_isolation(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid1, uid1 = _seed(db_session, "pfapi3a")
    _pid2, uid2 = _seed(db_session, "pfapi3b")
    _below(db_session, pid1, monkeypatch)
    sid = client.post(f"/projects/{pid1}/performance/analyze", headers=_h(uid1), json={}).json()[
        "snapshot"
    ]["id"]
    assert client.get(f"/performance/{sid}", headers=_h(uid2)).status_code == 404
    assert client.get(f"/performance/{sid}/metrics", headers=_h(uid2)).status_code == 404


def test_missing_snapshot_maps_to_404(client: TestClient, db_session: Session) -> None:
    _pid, uid = _seed(db_session, "pfapi4")
    assert client.get("/performance/999999", headers=_h(uid)).status_code == 404
