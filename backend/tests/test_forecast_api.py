"""Тесты REST API AI Business Forecasting Engine (v0.7.6, offline).

Project/forecast access (401 без токена); create/list/get/generate/metrics/roadmap/
business-outlook; tenant isolation (404 на чужое); missing → 404.
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


def _forecast(client: TestClient, pid: int, uid: int) -> int:
    r = client.post(f"/projects/{pid}/forecasts", headers=_h(uid), json={"horizon": "12_months"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


_ROUTES = [
    ("post", "/projects/1/forecasts"),
    ("get", "/projects/1/forecasts"),
    ("get", "/forecasts/1"),
    ("post", "/forecasts/1/generate"),
    ("get", "/forecasts/1/metrics"),
    ("get", "/forecasts/1/roadmap"),
    ("get", "/projects/1/business-outlook"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_create_and_list(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "fcapi1")
    fid = _forecast(client, pid, uid)
    assert fid > 0
    lst = client.get(f"/projects/{pid}/forecasts", headers=_h(uid)).json()
    assert len(lst["forecasts"]) == 1
    assert lst["summary"]["forecasts_total"] == 1


def test_generate_and_metrics(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "fcapi2")
    fid = _forecast(client, pid, uid)
    gen = client.post(f"/forecasts/{fid}/generate", headers=_h(uid), json={})
    assert gen.status_code == 200
    assert len(gen.json()["metrics"]) == 6
    assert gen.json()["roadmap"] is not None
    m = client.get(f"/forecasts/{fid}/metrics", headers=_h(uid)).json()
    assert len(m["metrics"]) == 6
    assert m["explanation"]["reasons"]


def test_get_and_roadmap(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "fcapi3")
    fid = _forecast(client, pid, uid)
    client.post(f"/forecasts/{fid}/generate", headers=_h(uid), json={})
    got = client.get(f"/forecasts/{fid}", headers=_h(uid))
    assert got.status_code == 200 and got.json()["forecast"]["id"] == fid
    rm = client.get(f"/forecasts/{fid}/roadmap", headers=_h(uid)).json()
    assert rm["roadmap"] is not None and len(rm["roadmap"]["quarters"]) == 4


def test_business_outlook(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "fcapi4")
    fid = _forecast(client, pid, uid)
    client.post(f"/forecasts/{fid}/generate", headers=_h(uid), json={})
    outlook = client.get(f"/projects/{pid}/business-outlook", headers=_h(uid))
    assert outlook.status_code == 200
    assert outlook.json()["forecast"]["id"] == fid


def test_tenant_isolation_blocks_foreign_forecast(client: TestClient, db_session: Session) -> None:
    pid1, uid1 = _seed(db_session, "fcapi5a")
    _pid2, uid2 = _seed(db_session, "fcapi5b")
    fid = _forecast(client, pid1, uid1)
    assert client.get(f"/forecasts/{fid}", headers=_h(uid2)).status_code == 404
    assert client.post(f"/forecasts/{fid}/generate", headers=_h(uid2), json={}).status_code == 404


def test_missing_forecast_maps_to_404(client: TestClient, db_session: Session) -> None:
    _pid, uid = _seed(db_session, "fcapi6")
    assert client.get("/forecasts/999999", headers=_h(uid)).status_code == 404


def test_unknown_horizon_maps_to_400(client: TestClient, db_session: Session) -> None:
    """Неизвестный горизонт (валидация сервиса) → 400, а не 500/404."""
    pid, uid = _seed(db_session, "fcapi7")
    r = client.post(f"/projects/{pid}/forecasts", headers=_h(uid), json={"horizon": "bogus"})
    assert r.status_code == 400, r.text
    assert "горизонт" in r.json()["detail"].lower()
