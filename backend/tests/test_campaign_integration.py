"""Интеграционные тесты AI Campaign Manager (v0.6.7): learning + strategy → кампания.

Проверяет, что кампания реально опирается на AI Learning Profile и Content Strategy,
и что apply создаёт только черновик, не трогая активный календарь и не включая live.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.autopilot_calendar_plan import AutopilotCalendarPlan
from app.models.content_strategy_profile import ContentStrategyProfile
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
from app.services.ai_campaign_manager_service import AICampaignManagerService
from app.services.ai_learning_service import AILearningService


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


def _seed_learning(db: Session, project_id: int, *, strong_format: str = "case") -> None:
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            title="Кейс производства",
            status="published",
            vk_text="x" * 700,
            hashtags=[strong_format],
            generation_notes={"selected_format": strong_format},
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
            impressions=10000,
            reach=9000,
            likes=400,
            comments=50,
            shares=120,
            saves=300,
            clicks=200,
            ctr=0.02,
            engagement_rate=0.09,
        ),
    )
    AILearningService(
        settings=Settings(media_proxy_public_base_url="https://m.example.com")
    ).analyze_project(db, project_id)


def test_campaign_reflects_learning_strong_format(db_session: Session) -> None:
    pid = _project(db_session, "cint1")
    _seed_learning(db_session, pid, strong_format="case")
    svc = _svc()
    cid = svc.create_campaign(db_session, pid, name="C", goal="sales")["id"]
    plan = svc.plan_campaign(db_session, cid)
    # Формат, который лучше заходит клиенту (case), присутствует в этапах и content_mix.
    assert any("case" in s["recommended_formats"] for s in plan["stages"])
    assert "case" in plan["strategy"]["content_mix"]


def test_campaign_builds_content_strategy_profile(db_session: Session) -> None:
    pid = _project(db_session, "cint2")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = svc.create_campaign(db_session, pid, name="C", goal="awareness")["id"]
    svc.plan_campaign(db_session, cid)
    # Планирование кампании прогоняет ContentStrategistService (создаёт профиль стратегии).
    assert db_session.query(ContentStrategyProfile).filter_by(project_id=pid).count() == 1


def test_apply_creates_draft_not_active_calendar(db_session: Session) -> None:
    pid = _project(db_session, "cint3")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = svc.create_campaign(db_session, pid, name="C", goal="launch")["id"]
    svc.plan_campaign(db_session, cid)
    svc.approve_campaign(db_session, cid)
    svc.apply_campaign(db_session, cid, confirmation="APPLY_CAMPAIGN")
    plans = db_session.query(AutopilotCalendarPlan).filter_by(project_id=pid).all()
    assert plans and all(p.status == "draft" for p in plans)


def test_goal_awareness_uses_short_funnel(db_session: Session) -> None:
    pid = _project(db_session, "cint4")
    _seed_learning(db_session, pid)
    svc = _svc()
    cid = svc.create_campaign(db_session, pid, name="C", goal="awareness")["id"]
    stages = svc.generate_campaign_plan(db_session, cid)
    # awareness-цель → короткая воронка awareness → interest.
    assert [s["stage_type"] for s in stages] == ["awareness", "interest"]
