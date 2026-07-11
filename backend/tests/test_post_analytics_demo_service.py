"""Тесты demo-аналитики постов (offline): анализ текста, оценки, источники, рекомендации."""

from sqlalchemy.orm import Session

from app.repositories import post_publication_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.schemas.project import ProjectCreate
from app.services.post_analytics_service import (
    SOURCE_DEMO,
    SOURCE_ESTIMATED,
    SOURCE_INTERNAL,
    PostAnalyticsService,
)

SVC = PostAnalyticsService()
_ALLOWED_SOURCES = {SOURCE_INTERNAL, SOURCE_ESTIMATED, SOURCE_DEMO}


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _post_with_pub(
    db: Session,
    project_id: int,
    platform: str,
    text: str,
    status: str = "published",
    media: bool = True,
):
    notes = {"media_asset_ids": [1, 2]} if media else {}
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            title="Мерч оптом",
            telegram_text=text if platform == "telegram" else "",
            vk_text=text if platform == "vk" else "",
            status=status,
            generation_notes=notes,
        ),
    )
    post_publication_repository.create_publication(
        db,
        PostPublicationCreate(
            post_id=post.id,
            project_id=project_id,
            platform=platform,
            status=status,
            external_url=f"https://{platform}.example/wall-1_{post.id}",
        ),
    )
    return post


def test_analyze_post_text_detects_signals() -> None:
    text = "Закажите футболки оптом! Цена от 500 руб. https://t.me/shop #мерч #опт"
    a = SVC.analyze_post_text(text)
    assert a["has_cta"] is True
    assert a["has_link"] is True
    assert a["hashtags_count"] == 2
    assert a["text_length"] == len(text)


def test_detect_helpers() -> None:
    assert SVC.detect_cta("подпишитесь на канал") is True
    assert SVC.detect_cta("просто текст без призыва") is False
    assert SVC.detect_links("см. https://vk.com/x") is True
    assert SVC.detect_hashtags("текст #a #бренд") == ["#a", "#бренд"]


def test_demo_analytics_returns_existing_publications(db_session: Session) -> None:
    project_id = _project(db_session)
    _post_with_pub(db_session, project_id, "vk", "Закажите мерч оптом! https://vk.com/x #опт")
    _post_with_pub(db_session, project_id, "telegram", "Новый дроп худи. Пишите в директ.")
    cards = SVC.build_demo_post_analytics(db_session, project_id)
    assert len(cards) == 2
    platforms = {c["platform"] for c in cards}
    assert platforms == {"vk", "telegram"}
    for c in cards:
        assert c["external_url"]
        assert c["publication_id"]
        assert set(c) >= {
            "post_id",
            "platform",
            "status",
            "estimated_views",
            "estimated_reach",
            "estimated_likes",
            "er_percent",
            "ctr_percent",
            "quality_score",
            "engagement_score",
            "source",
        }


def test_demo_analytics_platform_filter(db_session: Session) -> None:
    project_id = _project(db_session)
    _post_with_pub(db_session, project_id, "vk", "Опт мерч https://vk.com/x")
    _post_with_pub(db_session, project_id, "telegram", "TG пост")
    only_vk = SVC.build_demo_post_analytics(db_session, project_id, platform="vk")
    assert only_vk and all(c["platform"] == "vk" for c in only_vk)


def test_quality_and_engagement_bounded_and_source_valid(db_session: Session) -> None:
    project_id = _project(db_session)
    _post_with_pub(db_session, project_id, "vk", "Закажите мерч! Цена от 500 руб https://vk.com/x")
    for c in SVC.build_demo_post_analytics(db_session, project_id):
        assert 0 <= c["quality_score"] <= 100
        assert 0 <= c["engagement_score"] <= 100
        assert c["source"] in _ALLOWED_SOURCES
        # Без снапшота метрики — оценка (estimated), а не реальные API-данные.
        assert c["source"] == SOURCE_ESTIMATED
        assert c["estimated_reach"] <= c["estimated_views"]


def test_recommendations_generated(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post_with_pub(db_session, project_id, "vk", "Просто текст.", media=False)
    recs = SVC.build_recommendations(post)
    assert recs
    assert any("CTA" in r for r in recs)


def test_demo_summary_offline(db_session: Session) -> None:
    project_id = _project(db_session)
    _post_with_pub(db_session, project_id, "vk", "Опт мерч https://vk.com/x")
    _post_with_pub(db_session, project_id, "telegram", "TG", status="scheduled")
    summary = SVC.demo_analytics_summary(db_session, project_id)
    assert summary["total_posts"] == 2
    assert summary["published"] == 1
    assert summary["scheduled"] == 1
    assert 0 <= summary["avg_quality_score"] <= 100
    assert summary["live_calls"] is False
