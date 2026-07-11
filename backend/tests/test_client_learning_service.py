"""Тесты движка обучения клиента (v0.4.0)."""

from sqlalchemy.orm import Session

from app.models.post_analytics_snapshot import PostAnalyticsSnapshot
from app.repositories import client_learning_repository, post_repository, project_repository
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.client_learning_service import ClientLearningService


def _project(db: Session, slug: str) -> int:
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    return project.id


def _post(db: Session, project_id: int, text: str, hashtags: list[str], title: str = "Тема") -> int:
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            title=title,
            status="needs_review",
            vk_text=text,
            hashtags=hashtags,
        ),
    )
    return post.id


def test_default_profile_created(db_session: Session) -> None:
    pid = _project(db_session, "proj-a")
    svc = ClientLearningService()
    profile = svc.build_learning_profile(db_session, pid)
    assert profile.project_id == pid
    assert profile.profile_version >= 1
    assert profile.confidence_score == 0.0


def test_approved_feedback_increases_preferred_tag(db_session: Session) -> None:
    pid = _project(db_session, "proj-b")
    post_id = _post(db_session, pid, "Заказать мерч со скидкой 20%", ["мерч"], title="Мерч")
    svc = ClientLearningService()
    svc.record_review_feedback(db_session, post_id, "approved")
    profile = client_learning_repository.get_profile(db_session, pid, None)
    assert "мерч" in profile.high_performing_tags
    assert profile.approval_patterns["approved"] == 1


def test_rejected_feedback_increases_rejected_tag(db_session: Session) -> None:
    pid = _project(db_session, "proj-c")
    post_id = _post(db_session, pid, "Спамный текст", ["спам"], title="Спам")
    svc = ClientLearningService()
    svc.record_review_feedback(db_session, post_id, "rejected", reason_tags=["не та тема"])
    profile = client_learning_repository.get_profile(db_session, pid, None)
    assert "спам" in profile.low_performing_tags
    assert "Спам" in profile.rejected_topics
    assert profile.approval_patterns["rejected"] == 1


def test_edited_feedback_detects_shortened_and_added_cta(db_session: Session) -> None:
    pid = _project(db_session, "proj-d")
    post_id = _post(db_session, pid, "text", [], title="T")
    svc = ClientLearningService()
    before = "Очень длинный текст без всякого призыва к действию, просто описание товара " * 3
    after = "Коротко. Заказать сейчас!"
    svc.record_review_feedback(db_session, post_id, "edited", before_text=before, after_text=after)
    profile = client_learning_repository.get_profile(db_session, pid, None)
    assert profile.editing_patterns.get("shortened")
    assert profile.editing_patterns.get("added_cta")


def test_analytics_metrics_update_high_performing_tags(db_session: Session) -> None:
    pid = _project(db_session, "proj-e")
    post_id = _post(db_session, pid, "Пост про футболки", ["футболка"], title="Футболки")
    snap = PostAnalyticsSnapshot(
        post_id=post_id,
        project_id=pid,
        platform="vk",
        likes=100,
        engagement_rate=0.2,
        ctr=0.1,
    )
    db_session.add(snap)
    db_session.commit()
    svc = ClientLearningService()
    svc.build_learning_profile(db_session, pid)
    profile = client_learning_repository.get_profile(db_session, pid, None)
    assert "футболка" in profile.high_performing_tags


def test_confidence_increases_with_events(db_session: Session) -> None:
    pid = _project(db_session, "proj-f")
    svc = ClientLearningService()
    p0 = svc.build_learning_profile(db_session, pid)
    assert p0.confidence_score == 0.0
    for i in range(4):
        post_id = _post(db_session, pid, f"Текст {i} заказать", ["тег"], title=f"Тема {i}")
        svc.record_review_feedback(db_session, post_id, "approved")
    profile = client_learning_repository.get_profile(db_session, pid, None)
    assert profile.confidence_score > 0.0
    assert profile.updated_from_events_count == 4


def test_no_cross_project_mixing(db_session: Session) -> None:
    pid_a = _project(db_session, "proj-g1")
    pid_b = _project(db_session, "proj-g2")
    post_a = _post(db_session, pid_a, "Тег А", ["альфа"], title="A")
    svc = ClientLearningService()
    svc.record_review_feedback(db_session, post_a, "approved")
    svc.build_learning_profile(db_session, pid_b)
    profile_b = client_learning_repository.get_profile(db_session, pid_b, None)
    assert "альфа" not in profile_b.high_performing_tags
    assert profile_b.updated_from_events_count == 0


def test_score_content_candidate_uses_profile(db_session: Session) -> None:
    pid = _project(db_session, "proj-h")
    post_id = _post(db_session, pid, "Заказать мерч", ["мерч"], title="Мерч")
    svc = ClientLearningService()
    svc.record_review_feedback(db_session, post_id, "approved")
    result = svc.score_content_candidate(
        db_session, pid, None, {"vk_text": "Заказать мерч #мерч", "hashtags": ["мерч"]}
    )
    assert 0 <= result["quality_score"] <= 100
    assert "recommended_changes" in result


def test_summarize_learning_shape(db_session: Session) -> None:
    pid = _project(db_session, "proj-i")
    post_id = _post(db_session, pid, "Заказать мерч", ["мерч"], title="Мерч")
    svc = ClientLearningService()
    svc.record_review_feedback(db_session, post_id, "approved")
    summary = svc.summarize_learning(db_session, pid)
    assert summary["has_profile"] is True
    assert summary["event_counts"].get("approved") == 1
    assert "preferred_topics" in summary
