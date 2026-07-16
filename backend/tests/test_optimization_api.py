"""Тесты REST API — AI Autonomous Optimization (v0.8.1, offline).

Инварианты:
- analyze/list/get/experiment/validate работают; auth 401; отсутствующие сущности 404;
- эксперименты namespaced под /optimization-experiments (без коллизии с A/B /experiments).
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import continuous_improvement_repository as ci_repo
from app.schemas.project import ProjectCreate


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _seed(db: Session, pid: int) -> None:
    ci_repo.create_improvement(
        db,
        project_id=pid,
        account_id=None,
        title="Снять блокеры",
        priority="high",
        description="уменьшить зависимости",
    )


def test_analyze_and_list(client: TestClient, db_session: Session) -> None:
    pid, uid = _project(db_session, "api1")
    _seed(db_session, pid)
    r = client.post(f"/projects/{pid}/optimization/analyze", headers=_h(uid), json={})
    assert r.status_code == 200
    assert r.json()["optimizations"]
    lst = client.get(f"/projects/{pid}/optimizations", headers=_h(uid))
    assert lst.status_code == 200 and lst.json()["optimizations"]


def test_get_optimization_detail(client: TestClient, db_session: Session) -> None:
    pid, uid = _project(db_session, "api2")
    _seed(db_session, pid)
    opt = client.post(f"/projects/{pid}/optimization/analyze", headers=_h(uid), json={}).json()[
        "optimizations"
    ][0]
    r = client.get(f"/optimizations/{opt['id']}", headers=_h(uid))
    assert r.status_code == 200
    assert r.json()["optimization"]["id"] == opt["id"]
    assert r.json()["experiments"] == []


def test_experiment_and_validate(client: TestClient, db_session: Session) -> None:
    pid, uid = _project(db_session, "api3")
    _seed(db_session, pid)
    opt = client.post(f"/projects/{pid}/optimization/analyze", headers=_h(uid), json={}).json()[
        "optimizations"
    ][0]
    exp = client.post(f"/optimizations/{opt['id']}/experiment", headers=_h(uid), json={})
    assert exp.status_code == 200 and exp.json()["status"] == "draft"
    eid = exp.json()["id"]
    got = client.get(f"/optimization-experiments/{eid}", headers=_h(uid))
    assert got.status_code == 200 and got.json()["experiment"]["id"] == eid
    val = client.post(
        f"/optimization-experiments/{eid}/validate",
        headers=_h(uid),
        json={"actual_value": exp.json()["target_value"] + 5},
    )
    assert val.status_code == 200 and val.json()["validation"] == "success"


def test_auth_required(client: TestClient, db_session: Session) -> None:
    pid, _ = _project(db_session, "api4")
    assert client.post(f"/projects/{pid}/optimization/analyze").status_code == 401


def test_missing_optimization_404(client: TestClient, db_session: Session) -> None:
    _pid, uid = _project(db_session, "api5")
    assert client.get("/optimizations/999999", headers=_h(uid)).status_code == 404


def test_missing_experiment_404(client: TestClient, db_session: Session) -> None:
    _pid, uid = _project(db_session, "api6")
    assert (
        client.post(
            "/optimization-experiments/999999/validate", headers=_h(uid), json={}
        ).status_code
        == 404
    )
