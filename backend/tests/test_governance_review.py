"""Тесты review / approval flow — AI Optimization Governance (v0.8.2, offline).

Инварианты:
- submit_review создаёт GovernanceReview, статус identified → review;
- approve/reject меняют ТОЛЬКО статусы; повторная обработка запрещена; аудит.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import optimization_repository as opt_repo
from app.schemas.project import ProjectCreate
from app.services.ai_optimization_governance_service import (
    AIOptimizationGovernanceError,
    AIOptimizationGovernanceService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIOptimizationGovernanceService:
    return AIOptimizationGovernanceService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id, account.id


def _governance(db: Session, svc: AIOptimizationGovernanceService, slug: str) -> tuple[int, int]:
    pid, uid, aid = _project(db, slug)
    opt_repo.create_optimization(
        db, project_id=pid, account_id=aid, title="opt", optimization_score=60.0, priority="high"
    )
    gid = svc.run_governance_cycle(db, pid, user_id=uid)["governances"][0]["id"]
    return gid, uid


def test_submit_review_moves_status(db_session: Session) -> None:
    svc = _svc()
    gid, uid = _governance(db_session, svc, "gr1")
    review = svc.submit_review(
        db_session, gid, reviewer_user_id=uid, decision="approve", comment="ок", user_id=uid
    )
    assert review["decision"] == "approve"
    detail = svc.get_governance_detail(db_session, gid)
    assert detail["governance"]["status"] == "review"
    assert detail["governance"]["review_notes"] == "ок"
    assert len(detail["reviews"]) == 1


def test_approve_sets_status_only(db_session: Session) -> None:
    svc = _svc()
    gid, uid = _governance(db_session, svc, "gr2")
    out = svc.approve_optimization(db_session, gid, user_id=uid)
    assert out["approval_status"] == "approved" and out["status"] == "approved"


def test_reject_sets_status_only(db_session: Session) -> None:
    svc = _svc()
    gid, uid = _governance(db_session, svc, "gr3")
    out = svc.reject_optimization(db_session, gid, user_id=uid)
    assert out["approval_status"] == "rejected" and out["status"] == "rejected"


def test_double_process_rejected(db_session: Session) -> None:
    svc = _svc()
    gid, uid = _governance(db_session, svc, "gr4")
    svc.approve_optimization(db_session, gid, user_id=uid)
    with pytest.raises(AIOptimizationGovernanceError):
        svc.approve_optimization(db_session, gid, user_id=uid)
    with pytest.raises(AIOptimizationGovernanceError):
        svc.reject_optimization(db_session, gid, user_id=uid)


def test_audit_review_lifecycle(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    svc = _svc()
    gid, uid = _governance(db_session, svc, "gr5")
    svc.submit_review(db_session, gid, reviewer_user_id=uid, decision="approve", user_id=uid)
    svc.approve_optimization(db_session, gid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "governance.review_created" in actions
    assert "governance.approved" in actions
