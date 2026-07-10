"""Тесты сервиса аналитики постов (offline, без сети/секретов).

Анализ контента (CTA/ссылка/медиа/B2B), quality/engagement score, рекомендации,
источник метрик = estimated при отсутствии реальных данных.
"""

from sqlalchemy.orm import Session

from app.repositories import post_publication_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.schemas.project import ProjectCreate
from app.services.post_analytics_service import SOURCE_ESTIMATED, PostAnalyticsService


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _post(db: Session, project_id: int, text: str, status: str = "published", media: bool = False):
    notes = {"media_asset_ids": [1, 2]} if media else {}
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            title="Пост",
            telegram_text=text,
            vk_text="",
            instagram_text="",
            status=status,
            generation_notes=notes,
        ),
    )


def test_analyze_detects_cta_link_media(db_session: Session) -> None:
    project_id = _project(db_session)
    text = (
        "Закажите футболки оптом! Тираж от 50 штук, цена от 500 руб. "
        "Ссылка: https://t.me/shop\n\nПодробнее в директ. Успеете?"
    )
    post = _post(db_session, project_id, text, media=True)
    svc = PostAnalyticsService()
    content = svc.analyze_post_content(post)
    assert content.has_cta is True
    assert content.has_link is True
    assert content.has_question is True
    assert content.has_price_or_numbers is True
    assert content.has_media is True
    assert content.media_count == 2
    assert content.b2b_relevance_score >= 25  # «оптом»/«тираж»
    assert content.quality_score > 0


def test_quality_and_engagement_scores_bounded(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, "Короткий пост без ничего")
    svc = PostAnalyticsService()
    est = svc.estimate_post_metrics(post)
    assert 0 <= est.quality_score <= 100
    assert 0 <= est.engagement_score <= 100
    assert est.predicted_reach_level in ("low", "medium", "high")
    # Пост без медиа/CTA/ссылки — есть risk flags.
    assert "no_media" in est.risk_flags
    assert "no_cta" in est.risk_flags


def test_recommendations_present_for_weak_post(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, "Просто текст.")
    svc = PostAnalyticsService()
    content = svc.analyze_post_content(post)
    assert content.recommendations
    joined = " ".join(content.recommendations)
    assert "CTA" in joined
    assert "медиа" in joined or "media-group" in joined


def test_card_source_estimated_without_snapshot(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, "Текст с https://t.me/x и CTA закажите", media=True)
    post_publication_repository.create_publication(
        db_session,
        PostPublicationCreate(
            post_id=post.id, project_id=project_id, platform="telegram", status="published"
        ),
    )
    svc = PostAnalyticsService()
    card = svc.build_post_analytics_card(db_session, post.id, depth="deep")
    assert card["metrics_source"] == SOURCE_ESTIMATED
    assert card["cost_units"] == 40
    assert "recommendations" in card
    assert card["metrics"]["source"] == SOURCE_ESTIMATED


def test_calendar_counts_by_status(db_session: Session) -> None:
    project_id = _project(db_session)
    _post(db_session, project_id, "a", status="published")
    _post(db_session, project_id, "b", status="needs_review")
    svc = PostAnalyticsService()
    calendar = svc.build_calendar(db_session, project_id)
    total = {
        "published": sum(d["published_count"] for d in calendar["days"]),
        "needs_review": sum(d["needs_review_count"] for d in calendar["days"]),
    }
    assert total["published"] == 1
    assert total["needs_review"] == 1
