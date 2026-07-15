"""Тесты AI Campaign Manager (v0.6.7, offline).

Инварианты:
- кампания создаётся; стратегия учитывает AI Learning + Content Strategy;
- этапы и рекомендации создаются; approve обязателен; APPLY_CAMPAIGN обязателен;
- apply создаёт только draft; live не включается; tenant isolation; секретов нет.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.ai_campaign import AICampaign
from app.models.ai_campaign_stage import AICampaignStage
from app.models.autopilot_calendar_plan import AutopilotCalendarPlan
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
from app.services.ai_campaign_manager_service import (
    AICampaignError,
    AICampaignManagerService,
)
from app.services.ai_learning_service import AILearningService
from app.services.live_readiness_service import LiveReadinessService


def _svc() -> AICampaignManagerService:
    return AICampaignManagerService(
        settings=Settings(media_proxy_public_base_url="https://m.example.com")
    )


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _seed_learning(db: Session, project_id: int) -> None:
    for title, fmt, er, reach, saves in (
        ("Кейс производства", "case", 0.09, 10000, 300),
        ("Реклама скидок", "selling", 0.004, 1500, 1),
    ):
        post = post_repository.create_post(
            db,
            PostCreate(
                project_id=project_id,
                title=title,
                status="published",
                vk_text="x" * 600,
                hashtags=[fmt],
                generation_notes={"selected_format": fmt},
            ),
        )
        post.published_at = datetime(2026, 7, 10, 18, 0, tzinfo=UTC)
        db.commit()
        analytics_repository.create_snapshot(
            db,
            PostAnalyticsSnapshotInsert(
                post_id=post.id,
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
    AILearningService(
        settings=Settings(media_proxy_public_base_url="https://m.example.com")
    ).analyze_project(db, project_id)


def _campaign(
    db: Session, svc: AICampaignManagerService, project_id: int, goal: str = "sales"
) -> int:
    return svc.create_campaign(
        db,
        project_id,
        name="Кампания",
        goal=goal,
        product_context={"name": "Худи TEEON"},
    )["id"]


def test_create_campaign(db_session: Session) -> None:
    pid = _project(db_session, "camp1")
    svc = _svc()
    camp = svc.create_campaign(db_session, pid, name="Летняя", goal="sales")
    assert camp["status"] == "draft"
    assert camp["goal"] == "sales"
    assert db_session.query(AICampaign).filter_by(project_id=pid).count() == 1


def test_create_campaign_validates_goal(db_session: Session) -> None:
    pid = _project(db_session, "camp2")
    svc = _svc()
    with pytest.raises(AICampaignError):
        svc.create_campaign(db_session, pid, name="X", goal="bogus")
    with pytest.raises(AICampaignError):
        svc.create_campaign(db_session, pid, name="", goal="sales")


def test_plan_uses_learning_and_strategy(db_session: Session) -> None:
    pid = _project(db_session, "camp3")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = _campaign(db_session, svc, pid)
    plan = svc.plan_campaign(db_session, cid)
    # Content Strategy: сильная тема попадает в стратегию кампании.
    assert any("кейс" in str(t).lower() for t in plan["strategy"]["best_topics"])
    # AI Learning: сильный формат клиента (case) — в этапах кампании.
    assert any("case" in s["recommended_formats"] for s in plan["stages"])


def test_stages_created_by_goal_funnel(db_session: Session) -> None:
    pid = _project(db_session, "camp4")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = _campaign(db_session, svc, pid, goal="sales")
    stages = svc.generate_campaign_plan(db_session, cid)
    types = [s["stage_type"] for s in stages]
    # sales-воронка: awareness → interest → trust → conversion.
    assert types == ["awareness", "interest", "trust", "conversion"]
    assert db_session.query(AICampaignStage).filter_by(campaign_id=cid).count() == 4


def test_plan_regeneration_replaces_stages(db_session: Session) -> None:
    pid = _project(db_session, "camp4b")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = _campaign(db_session, svc, pid, goal="sales")
    svc.generate_campaign_plan(db_session, cid)
    svc.generate_campaign_plan(db_session, cid)  # повтор
    # Пере-генерация плана НЕ дублирует этапы.
    assert db_session.query(AICampaignStage).filter_by(campaign_id=cid).count() == 4


def test_recommendations_created_and_dedup(db_session: Session) -> None:
    pid = _project(db_session, "camp5")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = _campaign(db_session, svc, pid)
    recs = svc.generate_recommendations(db_session, cid)
    assert len(recs) >= 3
    recs2 = svc.generate_recommendations(db_session, cid)
    assert recs2 == []  # дедуп


def test_apply_requires_approve_and_confirmation(db_session: Session) -> None:
    pid = _project(db_session, "camp6")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = _campaign(db_session, svc, pid)
    svc.plan_campaign(db_session, cid)
    # apply до approve → ошибка.
    with pytest.raises(AICampaignError):
        svc.apply_campaign(db_session, cid, confirmation="APPLY_CAMPAIGN")
    svc.approve_campaign(db_session, cid)
    # approved, но без подтверждения → ошибка.
    with pytest.raises(AICampaignError):
        svc.apply_campaign(db_session, cid, confirmation="")
    with pytest.raises(AICampaignError):
        svc.apply_campaign(db_session, cid, confirmation="nope")


def test_apply_creates_draft_only_no_live(db_session: Session) -> None:
    pid = _project(db_session, "camp7")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = _campaign(db_session, svc, pid)
    svc.plan_campaign(db_session, cid)
    svc.approve_campaign(db_session, cid)
    res = svc.apply_campaign(db_session, cid, confirmation="APPLY_CAMPAIGN")
    assert res["calendar_draft_created"] is True
    assert res["live_enabled"] is False
    # Создан только ЧЕРНОВИК календаря (не активное расписание CrmPublishingPlan).
    plans = db_session.query(AutopilotCalendarPlan).filter_by(project_id=pid).all()
    assert len(plans) >= 1 and all(p.status == "draft" for p in plans)
    assert db_session.query(CrmPublishingPlan).filter_by(project_id=pid).count() == 0
    # Live не включён, публикаций нет.
    gate = LiveReadinessService(settings=svc._settings).build_effective_live_gate(
        db_session, pid, "telegram"
    )
    assert gate["can_publish_live"] is False
    assert gate["project_live_enabled"] is False
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0
    assert db_session.query(LivePublishAttempt).filter_by(status="published").count() == 0


def test_review_accept_reject(db_session: Session) -> None:
    pid = _project(db_session, "camp8")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = _campaign(db_session, svc, pid)
    recs = svc.generate_recommendations(db_session, cid)
    a = svc.accept_recommendation(db_session, cid, recs[0]["id"])
    assert a["status"] == "accepted"
    r = svc.reject_recommendation(db_session, cid, recs[1]["id"])
    assert r["status"] == "rejected"


def test_calendar_preview_no_write(db_session: Session) -> None:
    pid = _project(db_session, "camp9")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = _campaign(db_session, svc, pid)
    svc.plan_campaign(db_session, cid)
    before = db_session.query(AutopilotCalendarPlan).filter_by(project_id=pid).count()
    preview = svc.campaign_calendar_preview(db_session, cid)
    assert preview["writes"] is False
    assert len(preview["weeks"]) == 4
    after = db_session.query(AutopilotCalendarPlan).filter_by(project_id=pid).count()
    assert after == before


def test_tenant_isolation_recommendation(db_session: Session) -> None:
    pid_a = _project(db_session, "camp-a")
    pid_b = _project(db_session, "camp-b")
    _seed_learning(db_session, pid_a)
    svc = _svc()
    cid_a = _campaign(db_session, svc, pid_a)
    cid_b = _campaign(db_session, svc, pid_b)
    recs = svc.generate_recommendations(db_session, cid_a)
    rid = recs[0]["id"]
    # Кампания B не может трогать рекомендацию кампании A.
    with pytest.raises(AICampaignError):
        svc.accept_recommendation(db_session, cid_b, rid)


def test_explain_campaign(db_session: Session) -> None:
    pid = _project(db_session, "camp10")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = _campaign(db_session, svc, pid)
    svc.plan_campaign(db_session, cid)
    exp = svc.explain_campaign(db_session, cid)
    assert exp["reasons"]
    assert any("Продажи" in r for r in exp["reasons"])
