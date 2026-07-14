"""Тесты движка AI Learning Loop (v0.6.5, offline).

Инварианты:
- профиль создаётся; события пишутся; анализ и рекомендации работают;
- данные одного проекта НЕ попадают в другой;
- обучение НЕ включает live и НЕ публикует; секретов нет; reset не удаляет события.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.ai_learning_event import AILearningEvent
from app.models.ai_learning_profile import AILearningProfile
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
from app.services.live_readiness_service import LiveReadinessService


def _svc() -> AILearningService:
    return AILearningService(settings=Settings(media_proxy_public_base_url="https://m.example.com"))


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _post_with_metrics(
    db: Session,
    project_id: int,
    *,
    title: str,
    fmt: str,
    text_len: int,
    er: float,
    reach: int,
    saves: int,
    hour: int = 18,
) -> int:
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            title=title,
            status="published",
            vk_text="x" * text_len,
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
            comments=int(reach * er * 0.1),
            shares=int(reach * er * 0.2),
            saves=saves,
            clicks=int(reach * 0.02),
            ctr=0.02,
            engagement_rate=er,
        ),
    )
    return post.id


def test_get_or_create_profile_creates_row(db_session: Session) -> None:
    pid = _project(db_session, "aip1")
    profile = _svc().get_or_create_profile(db_session, pid)
    assert profile.id is not None
    assert profile.status == "learning"
    assert db_session.query(AILearningProfile).filter_by(project_id=pid).count() == 1
    # Идемпотентно: второй вызов возвращает ту же строку.
    again = _svc().get_or_create_profile(db_session, pid)
    assert again.id == profile.id
    assert db_session.query(AILearningProfile).filter_by(project_id=pid).count() == 1


def test_record_event_persists(db_session: Session) -> None:
    pid = _project(db_session, "aip2")
    svc = _svc()
    svc.record_event(db_session, pid, entity="post", event="save", value=120, source="analytics")
    assert db_session.query(AILearningEvent).filter_by(project_id=pid).count() == 1


def test_analyze_builds_profile_and_recommends(db_session: Session) -> None:
    pid = _project(db_session, "aip3")
    svc = _svc()
    _post_with_metrics(
        db_session, pid, title="Кейс", fmt="case", text_len=700, er=0.09, reach=10000, saves=300
    )
    _post_with_metrics(
        db_session, pid, title="FAQ", fmt="faq", text_len=90, er=0.005, reach=1500, saves=1, hour=9
    )
    res = svc.analyze_project(db_session, pid)
    assert res["learning_score"] > 0
    assert res["posts_with_metrics"] == 2
    assert "case" in res["preferred_formats"]
    # События из аналитики записаны.
    assert (
        db_session.query(AILearningEvent).filter_by(project_id=pid, source="analytics").count() > 0
    )
    rec = svc.recommend_next_content(db_session, pid)
    assert rec["recommended_formats"]
    assert rec["confidence"] == res["learning_score"]
    exp = svc.explain_learning(db_session, pid)
    assert exp["understood"]


def test_analyze_is_idempotent_no_duplicate_metric_events(db_session: Session) -> None:
    pid = _project(db_session, "aip4")
    svc = _svc()
    _post_with_metrics(
        db_session, pid, title="A", fmt="case", text_len=500, er=0.08, reach=8000, saves=200
    )
    svc.analyze_project(db_session, pid)
    n1 = db_session.query(AILearningEvent).filter_by(project_id=pid, source="analytics").count()
    svc.analyze_project(db_session, pid)  # повтор без изменений метрик
    n2 = db_session.query(AILearningEvent).filter_by(project_id=pid, source="analytics").count()
    assert n1 == n2


def test_tenant_isolation_between_projects(db_session: Session) -> None:
    pid_a = _project(db_session, "aip-a")
    pid_b = _project(db_session, "aip-b")
    svc = _svc()
    _post_with_metrics(
        db_session, pid_a, title="A", fmt="case", text_len=700, er=0.09, reach=9000, saves=250
    )
    svc.analyze_project(db_session, pid_a)
    # Профиль B не создан анализом A и пуст.
    prof_b = svc.get_or_create_profile(db_session, pid_b)
    assert prof_b.learning_score == 0.0
    assert list(prof_b.preferred_formats or []) == []
    # События проекта B отсутствуют.
    assert db_session.query(AILearningEvent).filter_by(project_id=pid_b).count() == 0


def test_learning_does_not_enable_live_or_publish(db_session: Session) -> None:
    pid = _project(db_session, "aip5")
    svc = _svc()
    _post_with_metrics(
        db_session, pid, title="A", fmt="case", text_len=700, er=0.09, reach=9000, saves=250
    )
    svc.analyze_project(db_session, pid)
    svc.record_client_feedback(db_session, pid, sentiment="excellent")
    # Live-гейт остаётся закрытым (обучение не трогает флаги готовности/глобальные).
    gate = LiveReadinessService(settings=svc._settings).build_effective_live_gate(
        db_session, pid, "telegram"
    )
    assert gate["can_publish_live"] is False
    assert gate["project_live_enabled"] is False
    # Ни одной реальной публикации/попытки.
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0
    assert db_session.query(LivePublishAttempt).filter_by(status="published").count() == 0


def test_reset_preserves_events(db_session: Session) -> None:
    pid = _project(db_session, "aip6")
    svc = _svc()
    _post_with_metrics(
        db_session, pid, title="A", fmt="case", text_len=700, er=0.09, reach=9000, saves=250
    )
    svc.analyze_project(db_session, pid)
    events_before = db_session.query(AILearningEvent).filter_by(project_id=pid).count()
    assert events_before > 0
    summary = svc.reset_learning(db_session, pid)
    assert summary["learning_score"] == 0.0
    assert summary["preferred_formats"] == []
    # История сигналов НЕ удалена.
    assert db_session.query(AILearningEvent).filter_by(project_id=pid).count() == events_before


def test_paused_profile_is_frozen(db_session: Session) -> None:
    pid = _project(db_session, "aip7")
    svc = _svc()
    _post_with_metrics(
        db_session, pid, title="A", fmt="case", text_len=700, er=0.09, reach=9000, saves=250
    )
    profile = svc.get_or_create_profile(db_session, pid)
    profile.status = "paused"
    db_session.commit()
    res = svc.update_client_learning(db_session, pid)
    # На паузе профиль не пересчитывается (score остаётся 0).
    assert res["status"] == "paused"
    assert res["learning_score"] == 0.0


def test_kill_switch_disables_recompute(db_session: Session) -> None:
    pid = _project(db_session, "aip8")
    svc = AILearningService(
        settings=Settings(
            media_proxy_public_base_url="https://m.example.com", ai_learning_enabled=False
        )
    )
    _post_with_metrics(
        db_session, pid, title="A", fmt="case", text_len=700, er=0.09, reach=9000, saves=250
    )
    res = svc.update_client_learning(db_session, pid)
    assert res["learning_score"] == 0.0


def test_feedback_records_client_signal(db_session: Session) -> None:
    pid = _project(db_session, "aip9")
    svc = _svc()
    out = svc.record_client_feedback(db_session, pid, sentiment="excellent", post_id=1)
    assert out["event_type"] == "client_rating"
    assert out["value"] == 1.0
    profile = svc.get_or_create_profile(db_session, pid)
    assert profile.total_feedback_events == 1
