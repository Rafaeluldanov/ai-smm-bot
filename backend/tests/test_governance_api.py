"""Тесты REST API — AI Optimization Governance (v0.8.2, offline).

Инварианты:
- analyze/list/detail/review/approve/reject/owner/portfolio работают; auth 401; отсутствующие 404;
- owner требует owner_user_id (400).
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import optimization_repository as opt_repo
from app.schemas.project import ProjectCreate


def _project(db: Session, slug: str) -> tuple[int, int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id, account.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _seed(db: Session, pid: int, aid: int) -> None:
    opt_repo.create_optimization(
        db, project_id=pid, account_id=aid, title="opt", optimization_score=60.0, priority="high"
    )


def test_analyze_and_list(client: TestClient, db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "ga1")
    _seed(db_session, pid, aid)
    r = client.post(f"/projects/{pid}/optimization-governance", headers=_h(uid), json={})
    assert r.status_code == 200 and r.json()["governances"]
    lst = client.get(f"/projects/{pid}/optimization-governance", headers=_h(uid))
    assert lst.status_code == 200 and lst.json()["governances"]


def test_detail_and_review_approve(client: TestClient, db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "ga2")
    _seed(db_session, pid, aid)
    gid = client.post(f"/projects/{pid}/optimization-governance", headers=_h(uid), json={}).json()[
        "governances"
    ][0]["id"]
    assert client.get(f"/governance/{gid}", headers=_h(uid)).status_code == 200
    rv = client.post(
        f"/governance/{gid}/review", headers=_h(uid), json={"decision": "approve", "comment": "ok"}
    )
    assert rv.status_code == 200
    ap = client.post(f"/governance/{gid}/approve", headers=_h(uid), json={})
    assert ap.status_code == 200 and ap.json()["approval_status"] == "approved"


def test_owner_and_portfolio(client: TestClient, db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "ga3")
    _seed(db_session, pid, aid)
    gid = client.post(f"/projects/{pid}/optimization-governance", headers=_h(uid), json={}).json()[
        "governances"
    ][0]["id"]
    ow = client.post(f"/governance/{gid}/owner", headers=_h(uid), json={"owner_user_id": uid})
    assert ow.status_code == 200 and ow.json()["owner_user_id"] == uid
    pf = client.get(f"/projects/{pid}/optimization-portfolio", headers=_h(uid))
    assert pf.status_code == 200 and pf.json()["metrics"]["total"] == 1


def test_owner_requires_user_id(client: TestClient, db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "ga4")
    _seed(db_session, pid, aid)
    gid = client.post(f"/projects/{pid}/optimization-governance", headers=_h(uid), json={}).json()[
        "governances"
    ][0]["id"]
    assert client.post(f"/governance/{gid}/owner", headers=_h(uid), json={}).status_code == 400


def test_auth_required(client: TestClient, db_session: Session) -> None:
    pid, _, _ = _project(db_session, "ga5")
    assert client.post(f"/projects/{pid}/optimization-governance").status_code == 401


def test_missing_governance_404(client: TestClient, db_session: Session) -> None:
    _pid, uid, _ = _project(db_session, "ga6")
    assert client.get("/governance/999999", headers=_h(uid)).status_code == 404
    assert client.post("/governance/999999/approve", headers=_h(uid), json={}).status_code == 404
