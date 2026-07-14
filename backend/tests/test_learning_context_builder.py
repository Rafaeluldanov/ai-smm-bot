"""Тесты LearningContextBuilder (v0.6.5): контекст обучения для генерации.

Проверяет: пустой контекст без профиля; заполненный контекст после обучения;
опциональная интеграция в генератор (preferred format применяется, поведение по
умолчанию не меняется).
"""

from sqlalchemy.orm import Session

from app.api.deps import get_post_generation_service
from app.models.topic import Topic
from app.repositories import (
    account_repository,
    ai_learning_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.services.learning_context_builder import LearningContextBuilder
from app.services.post_generation_service import PostGenerationService


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _generator() -> PostGenerationService:
    return get_post_generation_service()


def test_context_empty_without_profile(db_session: Session) -> None:
    pid = _project(db_session, "lcb1")
    ctx = LearningContextBuilder().build_context(db_session, pid)
    assert ctx["has_learning"] is False
    assert ctx["preferred_formats"] == []
    assert ctx["preferred_topics"] == []


def test_context_filled_from_profile(db_session: Session) -> None:
    pid = _project(db_session, "lcb2")
    profile = ai_learning_repository.get_or_create_profile(db_session, pid)
    ai_learning_repository.update_profile(
        db_session,
        profile,
        learning_score=80.0,
        preferred_topics=["Кейсы"],
        avoided_topics=["Скидки"],
        preferred_formats=["case"],
        preferred_styles=["подробный"],
        best_publish_times=["18:00"],
        cta_preferences={"preferred": ["Пишите в директ"]},
    )
    ctx = LearningContextBuilder().build_context(db_session, pid)
    assert ctx["has_learning"] is True
    assert ctx["preferred_formats"] == ["case"]
    assert ctx["forbidden_themes"] == ["Скидки"]
    assert ctx["preferred_tone"] == "подробный"
    assert ctx["best_time"] == "18:00"
    assert ctx["preferred_cta"] == ["Пишите в директ"]


def test_generator_applies_learning_format(db_session: Session) -> None:
    pid = _project(db_session, "lcb3")
    topic = Topic(project_id=pid, title="Как мы делаем мерч", cluster="", status="recommended")
    db_session.add(topic)
    db_session.commit()
    ctx = {"preferred_formats": ["case"], "preferred_cta": ["Напишите нам"]}
    result = _generator().generate_post_from_topic_object(db_session, topic, learning_context=ctx)
    from app.repositories import post_repository

    post = post_repository.get_post_by_id(db_session, result.post.id)
    assert post is not None
    assert post.generation_notes.get("selected_format") == "case"
    assert post.generation_notes.get("learning_context_applied") is True


def test_generator_default_behavior_unchanged(db_session: Session) -> None:
    pid = _project(db_session, "lcb4")
    topic = Topic(project_id=pid, title="Обычная тема", cluster="", status="recommended")
    db_session.add(topic)
    db_session.commit()
    # Без контекста обучения generation_notes остаётся пустым (поведение не меняется).
    result = _generator().generate_post_from_topic_object(db_session, topic)
    from app.repositories import post_repository

    post = post_repository.get_post_by_id(db_session, result.post.id)
    assert post is not None
    assert post.generation_notes == {}
