"""Тесты AI Sales & Lead Intelligence (v0.6.8, offline).

Инварианты:
- lead создаётся; attribution считается; revenue анализируется; связь с кампанией;
- learning используется; live не включается; tenant isolation; секретов нет.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.ai_lead_event import AILeadEvent
from app.models.content_revenue_attribution import ContentRevenueAttribution
from app.models.post_publication import PostPublication
from app.repositories import (
    account_repository,
    ai_learning_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.ai_sales_intelligence_service import (
    AISalesIntelligenceError,
    AISalesIntelligenceService,
)
from app.services.live_readiness_service import LiveReadinessService


def _svc() -> AISalesIntelligenceService:
    return AISalesIntelligenceService(
        settings=Settings(media_proxy_public_base_url="https://m.example.com")
    )


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _post(db: Session, project_id: int, title: str, cta: str = "") -> int:
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            title=title,
            status="published",
            vk_text="x",
            generation_notes={"cta": cta} if cta else {},
        ),
    ).id


def test_record_lead_event_persists(db_session: Session) -> None:
    pid = _project(db_session, "si1")
    svc = _svc()
    out = svc.record_lead_event(db_session, pid, event_type="lead_created", source_type="post")
    assert out["event_type"] == "lead_created"
    assert db_session.query(AILeadEvent).filter_by(project_id=pid).count() == 1


def test_record_lead_event_validates_type(db_session: Session) -> None:
    pid = _project(db_session, "si2")
    with pytest.raises(AISalesIntelligenceError):
        _svc().record_lead_event(db_session, pid, event_type="bogus")


def test_attribution_last_touch(db_session: Session) -> None:
    pid = _project(db_session, "si3")
    svc = _svc()
    a = _post(db_session, pid, "Пост A")
    b = _post(db_session, pid, "Пост B")
    svc.record_lead_event(
        db_session, pid, event_type="lead_created", post_id=a, metadata={"lead_ref": "L1"}
    )
    svc.record_lead_event(
        db_session, pid, event_type="deal_won", post_id=b, value=50000, metadata={"lead_ref": "L1"}
    )
    rows = svc.calculate_attribution(db_session, pid, model="last_touch")
    by_post = {r["post_id"]: r["revenue_value"] for r in rows}
    # last_touch: вся выручка — последнему касанию (пост B).
    assert by_post == {b: 50000.0}


def test_analyze_content_revenue(db_session: Session) -> None:
    pid = _project(db_session, "si4")
    svc = _svc()
    a = _post(db_session, pid, "Кейс", cta="получить расчёт")
    svc.record_lead_event(
        db_session, pid, event_type="deal_won", post_id=a, platform_key="telegram", value=30000
    )
    analysis = svc.analyze_content_revenue(db_session, pid)
    assert analysis["total_revenue"] == 30000.0
    assert analysis["top_content"][0]["post_id"] == a
    assert "получить расчёт" in analysis["best_cta"]
    assert analysis["best_platform"] == "telegram"


def test_campaign_link_and_score(db_session: Session) -> None:
    from app.models.ai_campaign import AICampaign

    pid = _project(db_session, "si5")
    svc = _svc()
    campaign = AICampaign(project_id=pid, name="Лето", goal="sales", status="active")
    db_session.add(campaign)
    db_session.commit()
    svc.record_lead_event(
        db_session, pid, event_type="deal_won", campaign_id=campaign.id, value=40000
    )
    analysis = svc.analyze_content_revenue(db_session, pid)
    assert analysis["top_campaigns"]
    tc = analysis["top_campaigns"][0]
    assert tc["campaign_id"] == campaign.id
    assert tc["campaign_revenue_score"] == 100.0  # единственная → лучшая


def test_learning_used_in_profile(db_session: Session) -> None:
    pid = _project(db_session, "si6")
    svc = _svc()
    # Тема нравится аудитории (AI Learning).
    lp = ai_learning_repository.get_or_create_profile(db_session, pid)
    ai_learning_repository.update_profile(db_session, lp, preferred_topics=["Кейс производства"])
    a = _post(db_session, pid, "Кейс производства")
    svc.record_lead_event(db_session, pid, event_type="deal_won", post_id=a, value=25000)
    profile = svc.build_sales_profile(db_session, pid)
    # Пересечение «нравится + продаёт».
    assert "Кейс производства" in profile["revenue_insights"]["topics_liked_and_selling"]


def test_build_profile_does_not_enable_live(db_session: Session) -> None:
    pid = _project(db_session, "si7")
    svc = _svc()
    a = _post(db_session, pid, "Кейс")
    svc.record_lead_event(db_session, pid, event_type="deal_won", post_id=a, value=10000)
    gate_before = LiveReadinessService(settings=svc._settings).build_effective_live_gate(
        db_session, pid, "telegram"
    )
    svc.build_sales_profile(db_session, pid)
    gate_after = LiveReadinessService(settings=svc._settings).build_effective_live_gate(
        db_session, pid, "telegram"
    )
    # Анализ не изменил live-гейт и не создал публикаций.
    assert gate_after == gate_before
    assert gate_after["can_publish_live"] is False
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_lead_event_rejects_foreign_post_or_campaign(db_session: Session) -> None:
    """Tenant isolation: нельзя привязать событие к посту/кампании чужого проекта."""
    from app.models.ai_campaign import AICampaign

    pid_a = _project(db_session, "si-fa")
    pid_b = _project(db_session, "si-fb")
    svc = _svc()
    foreign_post = _post(db_session, pid_a, "Секретный пост A")
    foreign_camp = AICampaign(project_id=pid_a, name="Секретная кампания A", goal="sales")
    db_session.add(foreign_camp)
    db_session.commit()
    with pytest.raises(AISalesIntelligenceError):
        svc.record_lead_event(
            db_session, pid_b, event_type="deal_won", post_id=foreign_post, value=100
        )
    with pytest.raises(AISalesIntelligenceError):
        svc.record_lead_event(
            db_session, pid_b, event_type="deal_won", campaign_id=foreign_camp.id, value=100
        )
    # Название чужого поста/кампании не утекает в анализ проекта B.
    analysis = svc.analyze_content_revenue(db_session, pid_b)
    assert "Секретный" not in str(analysis)


def test_total_revenue_consistent_with_summary(db_session: Session) -> None:
    """total_revenue не теряет campaign-only выручку и совпадает со сводкой."""
    from app.models.ai_campaign import AICampaign

    pid = _project(db_session, "si-tr")
    svc = _svc()
    a = _post(db_session, pid, "Пост")
    camp = AICampaign(project_id=pid, name="C", goal="sales", status="active")
    db_session.add(camp)
    db_session.commit()
    svc.record_lead_event(db_session, pid, event_type="deal_won", post_id=a, value=30000)
    svc.record_lead_event(db_session, pid, event_type="deal_won", campaign_id=camp.id, value=20000)
    rev = svc.get_revenue(db_session, pid)
    assert rev["analysis"]["total_revenue"] == 50000.0
    assert rev["summary"]["total_revenue"] == 50000.0


def test_reset_preserves_lead_events(db_session: Session) -> None:
    pid = _project(db_session, "si8")
    svc = _svc()
    a = _post(db_session, pid, "Кейс")
    svc.record_lead_event(db_session, pid, event_type="deal_won", post_id=a, value=10000)
    svc.build_sales_profile(db_session, pid)
    events_before = db_session.query(AILeadEvent).filter_by(project_id=pid).count()
    assert events_before == 1
    summary = svc.reset(db_session, pid)
    assert summary["status"] == "learning"
    # История событий лидов НЕ удалена; производная атрибуция очищена.
    assert db_session.query(AILeadEvent).filter_by(project_id=pid).count() == events_before
    assert db_session.query(ContentRevenueAttribution).filter_by(project_id=pid).count() == 0


def test_tenant_isolation_between_projects(db_session: Session) -> None:
    pid_a = _project(db_session, "si-a")
    pid_b = _project(db_session, "si-b")
    svc = _svc()
    a = _post(db_session, pid_a, "Кейс")
    svc.record_lead_event(db_session, pid_a, event_type="deal_won", post_id=a, value=10000)
    svc.build_sales_profile(db_session, pid_a)
    # Проект B пуст — нет событий/выручки.
    prof_b = svc.get_intelligence(db_session, pid_b)
    assert prof_b["revenue_summary"]["total_revenue"] == 0
    assert db_session.query(AILeadEvent).filter_by(project_id=pid_b).count() == 0


def test_recommend_and_explain(db_session: Session) -> None:
    pid = _project(db_session, "si9")
    svc = _svc()
    a = _post(db_session, pid, "Кейс производства", cta="получить расчёт")
    svc.record_lead_event(
        db_session, pid, event_type="deal_won", post_id=a, platform_key="telegram", value=50000
    )
    svc.build_sales_profile(db_session, pid)
    rec = svc.recommend_growth_actions(db_session, pid)
    assert rec["actions"]
    exp = svc.explain_revenue(db_session, pid)
    assert exp["total_revenue"] == 50000.0
    assert exp["reasons"]
