"""Тесты REST API AI Strategy Simulator (v0.7.5, offline).

Project/simulation/decision access (401 без токена); create/list/get/run/forecast;
compare-scenarios / strategy-recommendation; tenant isolation (404 на чужое).
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


def _decision_with_scenarios(client: TestClient, pid: int, uid: int) -> tuple[int, list[dict]]:
    r = client.post(
        f"/projects/{pid}/ai-decisions",
        headers=_h(uid),
        json={"decision_type": "growth", "title": "Рост"},
    )
    assert r.status_code == 200
    did = r.json()["id"]
    a = client.post(f"/ai-decisions/{did}/analyze", headers=_h(uid), json={})
    assert a.status_code == 200
    return did, a.json()["scenarios"]


def _simulation(client: TestClient, pid: int, uid: int, scenario_id: int) -> int:
    r = client.post(
        f"/projects/{pid}/simulations",
        headers=_h(uid),
        json={"scenario_id": scenario_id, "simulation_period": "90_days"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


_ROUTES = [
    ("post", "/projects/1/simulations"),
    ("get", "/projects/1/simulations"),
    ("get", "/simulations/1"),
    ("post", "/simulations/1/run"),
    ("get", "/simulations/1/forecast"),
    ("post", "/decisions/1/compare-scenarios"),
    ("get", "/decisions/1/strategy-recommendation"),
]


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_requires_auth(client: TestClient, method: str, path: str) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_create_and_list(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "stapi1")
    _did, scenarios = _decision_with_scenarios(client, pid, uid)
    sid = _simulation(client, pid, uid, scenarios[0]["id"])
    assert sid > 0
    lst = client.get(f"/projects/{pid}/simulations", headers=_h(uid)).json()
    assert len(lst["simulations"]) == 1
    assert lst["summary"]["simulations_total"] == 1


def test_run_and_forecast(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "stapi2")
    _did, scenarios = _decision_with_scenarios(client, pid, uid)
    sid = _simulation(client, pid, uid, scenarios[0]["id"])
    run = client.post(f"/simulations/{sid}/run", headers=_h(uid), json={})
    assert run.status_code == 200
    assert run.json()["simulation"]["status"] == "completed"
    assert len(run.json()["forecast"]) == 18
    fc = client.get(f"/simulations/{sid}/forecast", headers=_h(uid)).json()
    assert len(fc["forecast"]) == 18
    assert fc["explanation"]["reasons"]


def test_get_simulation(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "stapi3")
    _did, scenarios = _decision_with_scenarios(client, pid, uid)
    sid = _simulation(client, pid, uid, scenarios[0]["id"])
    got = client.get(f"/simulations/{sid}", headers=_h(uid))
    assert got.status_code == 200
    assert got.json()["simulation"]["id"] == sid


def test_compare_and_recommend(client: TestClient, db_session: Session) -> None:
    pid, uid = _seed(db_session, "stapi4")
    did, _sc = _decision_with_scenarios(client, pid, uid)
    cmp = client.post(f"/decisions/{did}/compare-scenarios", headers=_h(uid), json={})
    assert cmp.status_code == 200
    assert cmp.json()["winner_scenario_id"] is not None
    rec = client.get(f"/decisions/{did}/strategy-recommendation", headers=_h(uid))
    assert rec.status_code == 200
    assert rec.json()["winner"] is not None


def test_tenant_isolation_blocks_foreign_simulation(
    client: TestClient, db_session: Session
) -> None:
    pid1, uid1 = _seed(db_session, "stapi5a")
    _pid2, uid2 = _seed(db_session, "stapi5b")
    _did, scenarios = _decision_with_scenarios(client, pid1, uid1)
    sid = _simulation(client, pid1, uid1, scenarios[0]["id"])
    # Чужой пользователь не видит симуляцию проекта 1.
    assert client.get(f"/simulations/{sid}", headers=_h(uid2)).status_code == 404
    assert client.post(f"/simulations/{sid}/run", headers=_h(uid2), json={}).status_code == 404


def test_create_foreign_scenario_rejected(client: TestClient, db_session: Session) -> None:
    pid1, uid1 = _seed(db_session, "stapi6a")
    pid2, uid2 = _seed(db_session, "stapi6b")
    _did, scenarios = _decision_with_scenarios(client, pid1, uid1)
    # Пытаемся симулировать сценарий проекта 1 под проектом 2 (свой доступ, чужой сценарий).
    r = client.post(
        f"/projects/{pid2}/simulations",
        headers=_h(uid2),
        json={"scenario_id": scenarios[0]["id"]},
    )
    assert r.status_code == 400


def test_missing_scenario_maps_to_404(client: TestClient, db_session: Session) -> None:
    """Несуществующий сценарий (при доступе к проекту) → 404, а не 400/500."""
    pid, uid = _seed(db_session, "stapi7")
    r = client.post(f"/projects/{pid}/simulations", headers=_h(uid), json={"scenario_id": 999999})
    assert r.status_code == 404
