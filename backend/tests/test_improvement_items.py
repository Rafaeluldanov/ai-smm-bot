"""Тесты backlog улучшений + approve/reject — AI Continuous Improvement (v0.8.0, offline).

Инварианты:
- generate_improvements из паттернов (только предложения, статус identified);
- approve/reject меняют ТОЛЬКО статус (не применяют); повторная обработка запрещена; list; API.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import performance_repository as perf_repo
from app.schemas.project import ProjectCreate
from app.services.ai_continuous_improvement_service import (
    AIContinuousImprovementError,
    AIContinuousImprovementService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIContinuousImprovementService:
    return AIContinuousImprovementService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _with_improvements(db: Session, pid: int) -> list[dict]:
    snap = perf_repo.create_snapshot(
        db,
        project_id=pid,
        account_id=None,
        status="critical",
        performance_score=25.0,
        target_state={"revenue": 1000},
        actual_state={"revenue": 300},
    )
    perf_repo.create_deviation(
        db, snapshot_id=snap.id, metric="revenue", title="revenue -70%", impact="critical"
    )
    return _svc().run_learning_cycle(db, pid)["improvements"]


def test_improvements_generated_identified(db_session: Session) -> None:
    pid, _ = _project(db_session, "imp1")
    improvements = _with_improvements(db_session, pid)
    assert improvements and all(i["status"] == "identified" for i in improvements)
    assert all(i["priority"] in ("critical", "high", "medium", "low") for i in improvements)


def test_approve_sets_status_only(db_session: Session) -> None:
    pid, uid = _project(db_session, "imp2")
    imp = _with_improvements(db_session, pid)[0]
    out = _svc().approve_improvement(db_session, imp["id"], user_id=uid)
    assert out["status"] == "accepted"


def test_reject_sets_status_only(db_session: Session) -> None:
    pid, _ = _project(db_session, "imp3")
    imp = _with_improvements(db_session, pid)[0]
    out = _svc().reject_improvement(db_session, imp["id"])
    assert out["status"] == "rejected"


def test_double_process_rejected(db_session: Session) -> None:
    pid, _ = _project(db_session, "imp4")
    imp = _with_improvements(db_session, pid)[0]
    svc = _svc()
    svc.approve_improvement(db_session, imp["id"])
    with pytest.raises(AIContinuousImprovementError):
        svc.approve_improvement(db_session, imp["id"])
    with pytest.raises(AIContinuousImprovementError):
        svc.reject_improvement(db_session, imp["id"])


def test_list_by_status(db_session: Session) -> None:
    pid, _ = _project(db_session, "imp5")
    imps = _with_improvements(db_session, pid)
    _svc().approve_improvement(db_session, imps[0]["id"])
    accepted = _svc().get_improvements(db_session, pid, status="accepted")
    assert len(accepted) == 1


def test_audit_approve_reject(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "imp6")
    imps = _with_improvements(db_session, pid)
    svc = _svc()
    svc.approve_improvement(db_session, imps[0]["id"], user_id=uid)
    if len(imps) > 1:
        svc.reject_improvement(db_session, imps[1]["id"], user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "learning.improvement_approved" in actions


def test_approve_api(client: TestClient, db_session: Session) -> None:
    pid, uid = _project(db_session, "impapi1")
    imp = _with_improvements(db_session, pid)[0]
    r = client.post(f"/improvements/{imp['id']}/approve", headers=_h(uid), json={})
    assert r.status_code == 200 and r.json()["status"] == "accepted"


def test_missing_improvement_404(client: TestClient, db_session: Session) -> None:
    _pid, uid = _project(db_session, "impapi2")
    assert client.post("/improvements/999999/approve", headers=_h(uid), json={}).status_code == 404
