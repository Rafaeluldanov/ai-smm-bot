"""Тесты CEO Daily Brief и Intelligence Report пилота (v1.0.0, offline).

Инварианты (Part 6/7/15): brief содержит greeting/health/событие/риски/возможности/действия/прогноз;
intelligence — SWOT + AI-рекомендации; read-only (без данных — has_data=False, но не падает);
pilot_mode gate; аудит intelligence_generated/daily_brief_generated. Всё advisory.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.audit_log import AuditLogEntry
from app.repositories import account_repository, user_repository
from app.services.ai_business_context_service import AIBusinessContextService
from app.services.ai_business_pilot_service import PilotModeDisabledError
from app.services.ai_ceo_daily_brief_service import AICEODailyBriefService
from app.services.ai_pilot_intelligence_report_service import AIPilotIntelligenceReportService
from app.services.ai_pilot_onboarding_service import AIPilotOnboardingService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def _pilot(db: Session, slug: str) -> tuple[int, int]:
    aid, uid = _account(db, slug)
    pilot = AIPilotOnboardingService(settings=_SETTINGS).create_company_pilot(
        db,
        aid,
        company_name="TEEON Pilot",
        profile={
            "products": ["Футболки", "Худи"],
            "sales_channels": ["VK", "Instagram", "Site"],
            "current_revenue": 5_000_000.0,
            "target_revenue": 10_000_000.0,
        },
        user_id=uid,
    )
    return pilot["workspace"]["id"], uid


def test_context_swot(db_session: Session) -> None:
    wid, _uid = _pilot(db_session, "brf1")
    ctx = AIBusinessContextService(settings=_SETTINGS).analyze_company_context(db_session, wid)
    assert ctx["workspace_id"] == wid
    assert ctx["has_data"] is True
    assert any("продукт" in s for s in ctx["strengths"])
    assert any("канал" in s.lower() for s in ctx["strengths"])
    # KPI из дефолтного онбординга ниже цели → weakness.
    assert ctx["weaknesses"]


def test_intelligence_report(db_session: Session) -> None:
    wid, uid = _pilot(db_session, "brf2")
    report = AIPilotIntelligenceReportService(settings=_SETTINGS).generate_intelligence_report(
        db_session, wid, user_id=uid
    )
    assert "TEEON" in report["title"]
    assert report["company"]["current_revenue"] == 5_000_000.0
    assert report["company"]["target_revenue"] == 10_000_000.0
    assert report["ai_recommendations"]
    assert "current_state" in report


def test_daily_brief(db_session: Session) -> None:
    wid, uid = _pilot(db_session, "brf3")
    brief = AICEODailyBriefService(settings=_SETTINGS).generate_daily_brief(
        db_session, wid, user_id=uid
    )
    assert brief["greeting"] == "Доброе утро."
    assert brief["company_name"] == "TEEON Pilot"
    assert "health_score" in brief
    assert "main_event" in brief
    assert isinstance(brief["today_actions"], list) and len(brief["today_actions"]) <= 3
    # Без прогона AI-цепочки прогноза ещё нет — но структура есть.
    assert brief["forecast"]["available"] is False


def test_brief_pilot_mode_gate(db_session: Session) -> None:
    wid, uid = _pilot(db_session, "brf4")
    off = Settings(media_proxy_public_base_url="https://m.example.com", pilot_mode=False)
    with pytest.raises(PilotModeDisabledError):
        AICEODailyBriefService(settings=off).generate_daily_brief(db_session, wid, user_id=uid)


def test_brief_intelligence_audit(db_session: Session) -> None:
    wid, uid = _pilot(db_session, "brf5")
    AIPilotIntelligenceReportService(settings=_SETTINGS).generate_intelligence_report(
        db_session, wid, user_id=uid
    )
    AICEODailyBriefService(settings=_SETTINGS).generate_daily_brief(db_session, wid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "pilot.intelligence_generated" in actions
    assert "pilot.daily_brief_generated" in actions
