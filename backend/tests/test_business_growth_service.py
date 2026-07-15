"""Тесты AI Business Growth Agent (v0.6.9, offline).

Инварианты:
- growth profile создаётся; score считается; рекомендации создаются;
- revenue/content/campaign влияют; accept + APPLY_GROWTH_ACTION обязательны;
- apply не включает live и не меняет CRM; tenant isolation; секретов нет.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.business_growth_profile import BusinessGrowthProfile
from app.models.business_growth_recommendation import BusinessGrowthRecommendation
from app.models.crm_bot_smm import CrmPublishingPlan
from app.models.live_publish_attempt import LivePublishAttempt
from app.models.post_publication import PostPublication
from app.repositories import (
    account_repository,
    analytics_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.analytics import PostAnalyticsSnapshotInsert
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.ai_learning_service import AILearningService
from app.services.ai_sales_intelligence_service import AISalesIntelligenceService
from app.services.business_growth_agent_service import (
    BusinessGrowthAgentService,
    BusinessGrowthError,
)
from app.services.live_readiness_service import LiveReadinessService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> BusinessGrowthAgentService:
    return BusinessGrowthAgentService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _seed(db: Session, project_id: int, *, revenue: float = 60000) -> int:
    """Посты + метрики + обучение + событие выручки. Возвращает id топ-поста."""
    for title, fmt, er, reach, saves in (
        ("Кейс производства", "case", 0.09, 10000, 300),
        ("Реклама скидок", "selling", 0.004, 1500, 2),
    ):
        p = post_repository.create_post(
            db,
            PostCreate(
                project_id=project_id,
                title=title,
                status="published",
                vk_text="x" * 600,
                hashtags=[fmt],
                generation_notes={"selected_format": fmt, "cta": "получить расчёт"},
            ),
        )
        p.published_at = datetime(2026, 7, 10, 18, 0, tzinfo=UTC)
        db.commit()
        analytics_repository.create_snapshot(
            db,
            PostAnalyticsSnapshotInsert(
                post_id=p.id,
                project_id=project_id,
                platform="telegram",
                snapshot_at=datetime.now(UTC),
                impressions=reach,
                reach=reach,
                likes=int(reach * er * 0.5),
                comments=1,
                shares=int(reach * er * 0.2),
                saves=saves,
                clicks=int(reach * 0.02),
                ctr=0.02,
                engagement_rate=er,
            ),
        )
    AILearningService(settings=_SETTINGS).analyze_project(db, project_id)
    case_post = next(
        p
        for p in post_repository.list_posts(db, project_id=project_id)
        if p.title == "Кейс производства"
    )
    sales = AISalesIntelligenceService(settings=_SETTINGS)
    sales.record_lead_event(
        db, project_id, event_type="lead_created", post_id=case_post.id, platform_key="telegram"
    )
    sales.record_lead_event(
        db,
        project_id,
        event_type="deal_won",
        post_id=case_post.id,
        platform_key="telegram",
        value=revenue,
    )
    return case_post.id


def test_analyze_creates_profile(db_session: Session) -> None:
    pid = _project(db_session, "bg1")
    _seed(db_session, pid)
    res = _svc().analyze_business(db_session, pid)
    assert 0 <= res["growth_score"] <= 100
    assert res["strengths"] and res["opportunities"]
    profile = db_session.query(BusinessGrowthProfile).filter_by(project_id=pid).one()
    assert profile.status == "active"
    assert profile.last_analysis_at is not None


def test_revenue_affects_score(db_session: Session) -> None:
    pid_hi = _project(db_session, "bg-hi")
    pid_lo = _project(db_session, "bg-lo")
    _seed(db_session, pid_hi, revenue=100000)
    _seed(db_session, pid_lo, revenue=1000)
    svc = _svc()
    hi = svc.calculate_growth_score(db_session, pid_hi)
    lo = svc.calculate_growth_score(db_session, pid_lo)
    # Больше выручки → выше revenue-компонент → выше score.
    assert hi["components"]["revenue"] > lo["components"]["revenue"]
    assert hi["growth_score"] > lo["growth_score"]


def test_recommendations_created_and_dedup(db_session: Session) -> None:
    pid = _project(db_session, "bg2")
    _seed(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    assert len(recs) >= 1
    assert db_session.query(BusinessGrowthRecommendation).filter_by(project_id=pid).count() == len(
        recs
    )
    assert svc.generate_recommendations(db_session, pid) == []  # дедуп


def test_content_and_campaign_signals(db_session: Session) -> None:
    from app.models.ai_campaign import AICampaign

    pid = _project(db_session, "bg3")
    _seed(db_session, pid)
    # Кампания с выручкой → появляется возможность «повторить кампанию».
    campaign = AICampaign(project_id=pid, name="Летняя", goal="sales", status="active")
    db_session.add(campaign)
    db_session.commit()
    AISalesIntelligenceService(settings=_SETTINGS).record_lead_event(
        db_session, pid, event_type="deal_won", campaign_id=campaign.id, value=40000
    )
    opps = _svc().detect_growth_opportunities(db_session, pid)
    types = {o["type"] for o in opps}
    # content (масштабировать тему) + campaign (повторить кампанию) присутствуют.
    assert "content" in types
    assert "campaign" in types


def test_apply_requires_accept_and_confirmation(db_session: Session) -> None:
    pid = _project(db_session, "bg4")
    _seed(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    rid = recs[0]["id"]
    with pytest.raises(BusinessGrowthError):
        svc.apply_recommendation(db_session, pid, rid, confirmation="APPLY_GROWTH_ACTION")
    svc.accept_recommendation(db_session, pid, rid)
    with pytest.raises(BusinessGrowthError):
        svc.apply_recommendation(db_session, pid, rid, confirmation="")
    with pytest.raises(BusinessGrowthError):
        svc.apply_recommendation(db_session, pid, rid, confirmation="nope")
    res = svc.apply_recommendation(db_session, pid, rid, confirmation="APPLY_GROWTH_ACTION")
    assert res["live_enabled"] is False
    assert res["applied"]["growth_profile"] is True


def test_apply_does_not_touch_live_or_crm(db_session: Session) -> None:
    pid = _project(db_session, "bg5")
    _seed(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    rid = recs[0]["id"]
    svc.accept_recommendation(db_session, pid, rid)
    svc.apply_recommendation(db_session, pid, rid, confirmation="APPLY_GROWTH_ACTION")
    gate = LiveReadinessService(settings=_SETTINGS).build_effective_live_gate(
        db_session, pid, "telegram"
    )
    assert gate["can_publish_live"] is False
    assert gate["project_live_enabled"] is False
    # apply не активирует календарь/расписание и не публикует.
    assert db_session.query(CrmPublishingPlan).filter_by(project_id=pid).count() == 0
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0
    assert db_session.query(LivePublishAttempt).filter_by(status="published").count() == 0


def test_reject_recommendation(db_session: Session) -> None:
    pid = _project(db_session, "bg6")
    _seed(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    out = svc.reject_recommendation(db_session, pid, recs[0]["id"])
    assert out["status"] == "rejected"


def test_tenant_isolation_recommendation(db_session: Session) -> None:
    pid_a = _project(db_session, "bg-a")
    pid_b = _project(db_session, "bg-b")
    _seed(db_session, pid_a)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid_a)
    rid = recs[0]["id"]
    with pytest.raises(BusinessGrowthError):
        svc.accept_recommendation(db_session, pid_b, rid)
    with pytest.raises(BusinessGrowthError):
        svc.apply_recommendation(db_session, pid_b, rid, confirmation="APPLY_GROWTH_ACTION")


def test_explain_growth(db_session: Session) -> None:
    pid = _project(db_session, "bg7")
    _seed(db_session, pid)
    svc = _svc()
    svc.analyze_business(db_session, pid)
    exp = svc.explain_growth(db_session, pid)
    assert exp["reasons"]
    assert any("Growth Score" in r for r in exp["reasons"])
