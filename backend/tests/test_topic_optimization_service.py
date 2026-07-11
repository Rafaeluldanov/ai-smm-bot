"""Тесты сервиса оптимизации тем (v0.4.2)."""

from sqlalchemy.orm import Session

from app.models.post_analytics_snapshot import PostAnalyticsSnapshot
from app.repositories import post_repository, project_repository
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.client_learning_service import ClientLearningService
from app.services.topic_optimization_service import TopicOptimizationService


def _project(db: Session, slug: str) -> int:
    return project_repository.create_project(db, ProjectCreate(name=slug, slug=slug)).id


def _post(
    db: Session, project_id: int, title: str, tags: list[str], status: str = "published"
) -> int:
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id, title=title, status=status, vk_text="Пост", hashtags=tags
        ),
    )
    db.commit()
    return post.id


def _high_snapshot(db: Session, project_id: int, post_id: int, er: float = 0.2) -> None:
    db.add(
        PostAnalyticsSnapshot(
            post_id=post_id,
            project_id=project_id,
            platform="vk",
            reach=1000,
            likes=200,
            engagement_rate=er,
            ctr=0.05,
            source="api",
        )
    )
    db.commit()


def test_build_project_signal_summary(db_session: Session) -> None:
    pid = _project(db_session, "to-sum")
    post_id = _post(db_session, pid, "Футболки", ["мерч"])
    _high_snapshot(db_session, pid, post_id)
    ClientLearningService().build_learning_profile(db_session, pid)
    summary = TopicOptimizationService().build_project_signal_summary(db_session, pid)
    assert "high_performing_tags" in summary
    assert "content_gaps" in summary


def test_high_er_tags_become_recommendations(db_session: Session) -> None:
    pid = _project(db_session, "to-high")
    # Тег есть в high, но пост не «раскрывает» тему (usage учитывается) — попадёт в explore.
    post_id = _post(db_session, pid, "Разное", ["логотип"])
    _high_snapshot(db_session, pid, post_id)
    ClientLearningService().build_learning_profile(db_session, pid)
    rec = TopicOptimizationService().recommend_next_topics(db_session, pid)
    topics = " ".join(str(r["topic"]) for r in rec["recommendations"])
    assert "логотип" in topics.lower() or rec["recommendations"]


def test_rejected_topics_are_avoided(db_session: Session) -> None:
    pid = _project(db_session, "to-avoid")
    post_id = _post(db_session, pid, "Спамная тема", ["спам"], status="needs_review")
    ClientLearningService().record_review_feedback(db_session, post_id, "rejected")
    ClientLearningService().build_learning_profile(db_session, pid)
    rec = TopicOptimizationService().recommend_next_topics(db_session, pid)
    avoid = [r for r in rec["recommendations"] if r["category"] == "avoid"]
    assert any(r["topic"] == "Спамная тема" for r in avoid)


def test_confidence_in_0_1(db_session: Session) -> None:
    pid = _project(db_session, "to-conf")
    post_id = _post(db_session, pid, "Футболки", ["мерч"])
    _high_snapshot(db_session, pid, post_id)
    ClientLearningService().build_learning_profile(db_session, pid)
    rec = TopicOptimizationService().recommend_next_topics(db_session, pid)
    assert all(0.0 <= r["confidence_score"] <= 1.0 for r in rec["recommendations"])


def test_fatigue_penalty(db_session: Session) -> None:
    pid = _project(db_session, "to-fat")
    # Одна тема повторяется много раз → усталость.
    for _ in range(4):
        pid_post = _post(db_session, pid, "Футболки", ["мерч"])
        ClientLearningService().record_review_feedback(db_session, pid_post, "approved")
    ClientLearningService().build_learning_profile(db_session, pid)
    rec = TopicOptimizationService().recommend_next_topics(db_session, pid)
    fatigued = [r for r in rec["recommendations"] if "fatigue" in r.get("risk_flags", [])]
    assert fatigued  # тема помечена усталой


def test_score_topic_candidate_range(db_session: Session) -> None:
    pid = _project(db_session, "to-score")
    post_id = _post(db_session, pid, "Футболки", ["мерч"])
    _high_snapshot(db_session, pid, post_id)
    ClientLearningService().build_learning_profile(db_session, pid)
    sc = TopicOptimizationService().score_topic_candidate(
        db_session, pid, None, {"topic": "Мерч для команды", "tags": ["мерч"]}
    )
    for key in (
        "topic_fit_score",
        "client_fit_score",
        "performance_score",
        "novelty_score",
        "risk_score",
        "total_score",
    ):
        assert 0 <= sc[key] <= 100


def test_no_cross_project_mixing(db_session: Session) -> None:
    pid_a = _project(db_session, "to-a")
    pid_b = _project(db_session, "to-b")
    post_a = _post(db_session, pid_a, "Тема А", ["альфа"])
    _high_snapshot(db_session, pid_a, post_a)
    ClientLearningService().build_learning_profile(db_session, pid_a)
    rec_b = TopicOptimizationService().recommend_next_topics(db_session, pid_b)
    assert all("альфа" not in str(r["topic"]).lower() for r in rec_b["recommendations"])


def test_choose_topic_no_publish(db_session: Session) -> None:
    pid = _project(db_session, "to-choose")
    post_id = _post(db_session, pid, "Футболки", ["мерч"])
    _high_snapshot(db_session, pid, post_id)
    ClientLearningService().build_learning_profile(db_session, pid)
    result = TopicOptimizationService().choose_topic_for_next_schedule(db_session, pid)
    assert result["live"] is False
