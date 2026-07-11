"""Тесты влияния метрик на профиль обучения (v0.4.1)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.post_analytics_snapshot import PostAnalyticsSnapshot
from app.repositories import (
    client_learning_repository,
    post_repository,
    project_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.client_learning_service import ClientLearningService


def _project(db: Session, slug: str) -> int:
    return project_repository.create_project(db, ProjectCreate(name=slug, slug=slug)).id


def _post(db: Session, project_id: int, tags: list[str], hour: int = 18) -> int:
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            title="Тема",
            status="published",
            vk_text="Пост",
            hashtags=tags,
        ),
    )
    post.scheduled_at = datetime(2026, 7, 13, hour, 0, tzinfo=UTC)
    db.commit()
    return post.id


def _snapshot(
    db: Session, project_id: int, post_id: int, er: float, source: str = "api", **metrics
) -> None:
    snap = PostAnalyticsSnapshot(
        post_id=post_id,
        project_id=project_id,
        platform="vk",
        engagement_rate=er,
        ctr=metrics.pop("ctr", 0.03),
        source=source,
        **metrics,
    )
    db.add(snap)
    db.commit()


def test_high_er_updates_high_performing_tags(db_session: Session) -> None:
    pid = _project(db_session, "lf-high")
    post_id = _post(db_session, pid, ["мерч"])
    _snapshot(db_session, pid, post_id, er=0.18, likes=100, reach=1000)
    profile = ClientLearningService().build_learning_profile(db_session, pid)
    assert "мерч" in profile.high_performing_tags


def test_low_er_updates_low_performing_tags(db_session: Session) -> None:
    pid = _project(db_session, "lf-low")
    post_id = _post(db_session, pid, ["скучно"])
    _snapshot(db_session, pid, post_id, er=0.005, likes=1, reach=1000)
    profile = ClientLearningService().build_learning_profile(db_session, pid)
    assert "скучно" in profile.low_performing_tags


def test_best_publish_time_detected(db_session: Session) -> None:
    pid = _project(db_session, "lf-time")
    post_id = _post(db_session, pid, ["утро"], hour=9)
    _snapshot(db_session, pid, post_id, er=0.2, likes=200, reach=1000)
    profile = ClientLearningService().build_learning_profile(db_session, pid)
    assert "9:00" in profile.best_publish_times


def test_source_confidence_order_weights_api_over_demo(db_session: Session) -> None:
    # Тот же тег: api high-ER (+2) против demo low-ER (-1) → должен остаться сильным.
    pid = _project(db_session, "lf-conf")
    p1 = _post(db_session, pid, ["тег"])
    p2 = _post(db_session, pid, ["тег"])
    _snapshot(db_session, pid, p1, er=0.18, likes=100, reach=1000, source="api")
    _snapshot(db_session, pid, p2, er=0.005, likes=1, reach=1000, source="demo")
    profile = ClientLearningService().build_learning_profile(db_session, pid)
    # api boost (+2) > demo penalty (max(1, round(2*0.2))=1) → net положительный.
    assert "тег" in profile.high_performing_tags


def test_useful_content_signal(db_session: Session) -> None:
    pid = _project(db_session, "lf-useful")
    post_id = _post(db_session, pid, ["полезно"])
    _snapshot(db_session, pid, post_id, er=0.2, likes=100, reach=1000, saves=50, shares=40)
    profile = ClientLearningService().build_learning_profile(db_session, pid)
    assert profile.performance_patterns.get("useful_content_signals")


def test_recommendations_updated_from_metrics(db_session: Session) -> None:
    pid = _project(db_session, "lf-rec")
    post_id = _post(db_session, pid, ["мерч"])
    _snapshot(db_session, pid, post_id, er=0.2, likes=200, reach=1000)
    profile = ClientLearningService().build_learning_profile(db_session, pid)
    assert profile.recommendations
    assert any("тег" in r.lower() for r in profile.recommendations)


def test_explain_learning_changes(db_session: Session) -> None:
    pid = _project(db_session, "lf-explain")
    svc = ClientLearningService()
    before = svc.summarize_learning(db_session, pid)
    post_id = _post(db_session, pid, ["мерч"])
    _snapshot(db_session, pid, post_id, er=0.2, likes=200, reach=1000)
    svc.build_learning_profile(db_session, pid)
    after = svc.summarize_learning(db_session, pid)
    changes = svc.explain_learning_changes(before, after)
    assert changes
    assert any("тег" in c.lower() or "ER" in c for c in changes)


def test_no_cross_project_mixing_in_metrics(db_session: Session) -> None:
    pid_a = _project(db_session, "lf-xa")
    pid_b = _project(db_session, "lf-xb")
    post_a = _post(db_session, pid_a, ["альфа"])
    _snapshot(db_session, pid_a, post_a, er=0.2, likes=200, reach=1000)
    ClientLearningService().build_learning_profile(db_session, pid_b)
    profile_b = client_learning_repository.get_profile(db_session, pid_b, None)
    assert "альфа" not in (profile_b.high_performing_tags if profile_b else [])
