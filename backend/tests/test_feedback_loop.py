"""Тесты feedback loop пилота (v1.0.0, offline).

Инварианты (Part 8/9/15): решения владельца (accepted/rejected/modified) ТОЛЬКО сохраняются — бизнес
не меняется, KPI/цели не трогаются, рекомендация не выполняется; неизвестное решение → ошибка;
record_result дописывает результат; pilot_mode gate; аудит feedback_created.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.audit_log import AuditLogEntry
from app.repositories import account_repository, user_repository
from app.repositories import pilot_repository as repo
from app.services.ai_business_pilot_service import AIBusinessPilotError, PilotModeDisabledError
from app.services.ai_pilot_feedback_service import AIPilotFeedbackService
from app.services.ai_pilot_onboarding_service import AIPilotOnboardingService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_FEEDBACK_KEYS = {
    "id",
    "workspace_id",
    "recommendation_id",
    "decision",
    "comment",
    "result",
    "created_at",
}


def _svc(settings: Settings = _SETTINGS) -> AIPilotFeedbackService:
    return AIPilotFeedbackService(settings=settings)


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def _workspace(db: Session, slug: str) -> tuple[int, int]:
    aid, uid = _account(db, slug)
    pilot = AIPilotOnboardingService(settings=_SETTINGS).create_company_pilot(
        db, aid, company_name="Co", user_id=uid
    )
    return pilot["workspace"]["id"], uid


def test_accept_and_reject(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "fb1")
    svc = _svc()
    acc = svc.accept_recommendation(db_session, wid, comment="Беру", user_id=uid)
    assert acc["decision"] == "accepted" and acc["comment"] == "Беру"
    assert set(acc) == _FEEDBACK_KEYS
    rej = svc.reject_recommendation(db_session, wid, comment="Нет", user_id=uid)
    assert rej["decision"] == "rejected"
    assert len(svc.list_feedback(db_session, wid)) == 2


def test_record_result(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "fb2")
    svc = _svc()
    fb = svc.accept_recommendation(db_session, wid, user_id=uid)
    updated = svc.record_result(db_session, fb["id"], result="Выручка +10%", user_id=uid)
    assert updated["result"] == "Выручка +10%"


def test_record_result_is_audited(db_session: Session) -> None:
    """record_result — тоже мутация → должна писать в AuditLog (pilot.feedback_updated)."""
    wid, uid = _workspace(db_session, "fb2b")
    svc = _svc()
    fb = svc.accept_recommendation(db_session, wid, user_id=uid)
    svc.record_result(db_session, fb["id"], result="Готово", user_id=uid)
    actions = [e.action for e in db_session.query(AuditLogEntry).all()]
    assert "pilot.feedback_updated" in actions


def test_invalid_decision(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "fb3")
    with pytest.raises(AIBusinessPilotError):
        _svc().submit_feedback(db_session, wid, decision="approve_and_execute", user_id=uid)


def test_feedback_does_not_mutate_business(db_session: Session) -> None:
    """Feedback НЕ трогает goals/kpis/profile — только пишет в pilot_feedbacks."""
    wid, uid = _workspace(db_session, "fb4")
    goals_before = [
        (g.current_value, g.target_value, g.status) for g in repo.list_goals(db_session, wid)
    ]
    kpis_before = [
        (k.current_value, k.target_value, k.status) for k in repo.list_kpis(db_session, wid)
    ]
    _svc().accept_recommendation(db_session, wid, recommendation_id=42, user_id=uid)
    goals_after = [
        (g.current_value, g.target_value, g.status) for g in repo.list_goals(db_session, wid)
    ]
    kpis_after = [
        (k.current_value, k.target_value, k.status) for k in repo.list_kpis(db_session, wid)
    ]
    assert goals_before == goals_after
    assert kpis_before == kpis_after


def test_feedback_pilot_mode_gate(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "fb5")
    off = Settings(media_proxy_public_base_url="https://m.example.com", pilot_mode=False)
    with pytest.raises(PilotModeDisabledError):
        _svc(off).accept_recommendation(db_session, wid, user_id=uid)


def test_feedback_audit(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "fb6")
    _svc().accept_recommendation(db_session, wid, user_id=uid)
    actions = [e.action for e in db_session.query(AuditLogEntry).all()]
    assert "pilot.feedback_created" in actions
