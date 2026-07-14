"""Тесты автономного контент-стратега (v0.6.6, offline).

Инварианты:
- снапшот/рекомендации создаются; score считается; learning используется;
- apply требует accepted + confirmation; apply НЕ включает live и НЕ публикует;
- tenant isolation; секретов нет; reject/accept работают; дедуп рекомендаций.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.content_strategy_profile import ContentStrategyProfile
from app.models.content_strategy_recommendation import ContentStrategyRecommendation
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
from app.services.content_strategist_service import (
    ContentStrategistError,
    ContentStrategistService,
)
from app.services.live_readiness_service import LiveReadinessService


def _svc() -> ContentStrategistService:
    return ContentStrategistService(
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
    """Создать посты+метрики и прогнать обучение, чтобы у стратегии были сигналы."""
    for title, fmt, er, reach, saves, hour in (
        ("Кейс производства", "case", 0.09, 10000, 300, 18),
        ("Реклама скидок", "selling", 0.004, 1500, 1, 9),
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
        post.published_at = datetime(2026, 7, 10, hour, 0, tzinfo=UTC)
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


def test_snapshot_created_and_persists_profile(db_session: Session) -> None:
    pid = _project(db_session, "css1")
    _seed_learning(db_session, pid)
    snap = _svc().build_strategy_snapshot(db_session, pid)
    assert snap["project_id"] == pid
    assert snap["recommended_frequency"]
    profile = db_session.query(ContentStrategyProfile).filter_by(project_id=pid).one()
    assert profile.status == "active"
    assert profile.last_strategy_update is not None


def test_learning_used_in_snapshot(db_session: Session) -> None:
    pid = _project(db_session, "css2")
    _seed_learning(db_session, pid)
    snap = _svc().build_strategy_snapshot(db_session, pid)
    # Сильная тема из обучения попадает в best_topics.
    assert any("кейс" in str(t).lower() for t in snap["best_topics"])
    assert "case" in snap["best_formats"]


def test_score_topic_components(db_session: Session) -> None:
    pid = _project(db_session, "css3")
    _seed_learning(db_session, pid)
    res = _svc().score_topic(db_session, pid, "Кейс производства")
    assert 0 <= res["score"] <= 100
    comps = res["components"]
    assert set(comps) == {"learning", "analytics", "business", "seo", "trend"}
    # Тема из сильных обучения → максимум learning-компонента.
    assert comps["learning"] == 25.0


def test_generate_recommendations_and_dedup(db_session: Session) -> None:
    pid = _project(db_session, "css4")
    _seed_learning(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    assert len(recs) >= 1
    assert db_session.query(ContentStrategyRecommendation).filter_by(project_id=pid).count() == len(
        recs
    )
    # Повторный вызов не плодит дубли (те же title/type ещё в generated).
    recs2 = svc.generate_recommendations(db_session, pid)
    assert recs2 == []


def test_apply_requires_accept_and_confirmation(db_session: Session) -> None:
    pid = _project(db_session, "css5")
    _seed_learning(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    rid = recs[0]["id"]
    # apply до accept → ошибка.
    with pytest.raises(ContentStrategistError):
        svc.apply_recommendation(db_session, pid, rid, confirmation="APPLY_STRATEGY")
    svc.accept_recommendation(db_session, pid, rid)
    # accepted, но без подтверждения → ошибка.
    with pytest.raises(ContentStrategistError):
        svc.apply_recommendation(db_session, pid, rid, confirmation="")
    with pytest.raises(ContentStrategistError):
        svc.apply_recommendation(db_session, pid, rid, confirmation="nope")
    # accepted + APPLY_STRATEGY → успех.
    res = svc.apply_recommendation(db_session, pid, rid, confirmation="APPLY_STRATEGY")
    assert res["live_enabled"] is False


def test_apply_does_not_enable_live_or_publish(db_session: Session) -> None:
    pid = _project(db_session, "css6")
    _seed_learning(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    # Применяем topic-рекомендацию (меняет только content_rules).
    topic_rec = next(r for r in recs if r["recommendation_type"] == "topic")
    svc.accept_recommendation(db_session, pid, topic_rec["id"])
    svc.apply_recommendation(db_session, pid, topic_rec["id"], confirmation="APPLY_STRATEGY")
    gate = LiveReadinessService(settings=svc._settings).build_effective_live_gate(
        db_session, pid, "telegram"
    )
    assert gate["can_publish_live"] is False
    assert gate["project_live_enabled"] is False
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0
    assert db_session.query(LivePublishAttempt).filter_by(status="published").count() == 0


def test_reject_recommendation(db_session: Session) -> None:
    pid = _project(db_session, "css7")
    _seed_learning(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    out = svc.reject_recommendation(db_session, pid, recs[0]["id"])
    assert out["status"] == "rejected"


def test_next_month_and_explain(db_session: Session) -> None:
    pid = _project(db_session, "css8")
    _seed_learning(db_session, pid)
    svc = _svc()
    month = svc.recommend_next_month(db_session, pid)
    assert len(month["weeks"]) == 4
    assert all("theme" in w and "topics" in w and "formats" in w for w in month["weeks"])
    exp = svc.explain_strategy(db_session, pid)
    assert exp["reasons"]


def test_tenant_isolation_recommendation(db_session: Session) -> None:
    pid_a = _project(db_session, "css-a")
    pid_b = _project(db_session, "css-b")
    _seed_learning(db_session, pid_a)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid_a)
    rid = recs[0]["id"]
    # Проект B не может трогать рекомендацию проекта A.
    with pytest.raises(ContentStrategistError):
        svc.accept_recommendation(db_session, pid_b, rid)
    with pytest.raises(ContentStrategistError):
        svc.apply_recommendation(db_session, pid_b, rid, confirmation="APPLY_STRATEGY")


def test_calendar_preview_does_not_write(db_session: Session) -> None:
    from app.models.autopilot_calendar_plan import AutopilotCalendarPlan

    pid = _project(db_session, "css9")
    _seed_learning(db_session, pid)
    svc = _svc()
    before = db_session.query(AutopilotCalendarPlan).filter_by(project_id=pid).count()
    preview = svc.calendar_strategy_preview(db_session, pid)
    assert preview["writes"] is False
    # happy-path: превью реально построено (не сработал fallback на исключении).
    assert preview["recommended"]
    after = db_session.query(AutopilotCalendarPlan).filter_by(project_id=pid).count()
    assert after == before  # превью ничего не пишет


def test_apply_topic_mutates_content_rules_and_preserves_guardrails(
    db_session: Session,
) -> None:
    """apply topic-рекомендации добавляет preferred_topics, но НЕ затирает forbidden_phrases."""
    from app.repositories import autopilot_repository
    from app.services.autopilot_service import AutopilotService

    pid = _project(db_session, "css10")
    _seed_learning(db_session, pid)
    # Заранее настроенные правила с guardrail forbidden_phrases + бизнес-цель.
    AutopilotService().configure_content_rules(
        db_session,
        pid,
        {"business_goal": "sales", "forbidden_phrases": ["гарантия 100%"], "tone": "дружелюбный"},
    )
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    topic_rec = next(r for r in recs if r["recommendation_type"] == "topic")
    svc.accept_recommendation(db_session, pid, topic_rec["id"])
    res = svc.apply_recommendation(db_session, pid, topic_rec["id"], confirmation="APPLY_STRATEGY")
    assert res["applied"]["content_rules"] is True
    rules = autopilot_repository.get_profile_by_project_id(db_session, pid).content_rules
    # Позитивный эффект: тема реально добавлена в правила.
    assert rules.get("preferred_topics")
    # Guardrail и бизнес-цель НЕ затёрты слиянием.
    assert rules.get("forbidden_phrases") == ["гарантия 100%"]
    assert rules.get("business_goal") == "sales"


def test_apply_schedule_creates_calendar_draft_only(db_session: Session) -> None:
    """apply schedule-рекомендации создаёт ЧЕРНОВИК календаря (status=draft), не активный."""
    from app.models.autopilot_calendar_plan import AutopilotCalendarPlan

    pid = _project(db_session, "css11")
    _seed_learning(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    sched = next(r for r in recs if r["recommendation_type"] == "schedule")
    svc.accept_recommendation(db_session, pid, sched["id"])
    res = svc.apply_recommendation(db_session, pid, sched["id"], confirmation="APPLY_STRATEGY")
    assert res["applied"]["calendar_draft"] is True
    plans = db_session.query(AutopilotCalendarPlan).filter_by(project_id=pid).all()
    assert len(plans) >= 1
    # Все планы — только черновики (не активированы в реальное расписание).
    assert all(p.status == "draft" for p in plans)


def test_generate_after_apply_does_not_duplicate(db_session: Session) -> None:
    """Повторный generate после apply НЕ пересоздаёт уже применённые рекомендации."""
    from app.models.content_strategy_recommendation import ContentStrategyRecommendation

    pid = _project(db_session, "css12")
    _seed_learning(db_session, pid)
    svc = _svc()
    recs = svc.generate_recommendations(db_session, pid)
    sched = next(r for r in recs if r["recommendation_type"] == "schedule")
    svc.accept_recommendation(db_session, pid, sched["id"])
    svc.apply_recommendation(db_session, pid, sched["id"], confirmation="APPLY_STRATEGY")
    total_before = db_session.query(ContentStrategyRecommendation).filter_by(project_id=pid).count()
    svc.generate_recommendations(db_session, pid)  # повтор
    total_after = db_session.query(ContentStrategyRecommendation).filter_by(project_id=pid).count()
    # applied/rejected рекомендации не пересоздаются как новые дубли.
    assert total_after == total_before
