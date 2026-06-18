"""Тесты сервиса генерации постов."""

from sqlalchemy.orm import Session

from app.api.deps import get_post_generation_service
from app.repositories import media_asset_repository as media_repo
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import create_topic
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.post import WeeklyPostGenerationRequest
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _topic(db: Session, project_id: int, cluster: str = "футболки") -> int:
    return create_topic(
        db,
        TopicCreate(
            project_id=project_id,
            title="Футболки с логотипом на заказ",
            cluster=cluster,
            seo_keywords=["футболки с логотипом", "футболки на заказ"],
            status="recommended",
        ),
    ).id


def _approved_media(db: Session, project_id: int) -> None:
    media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="f.jpg",
            yandex_disk_path="disk:/f.jpg",
            status="approved",
            tags={"products": ["футболка"]},
        ),
    )


def test_generate_creates_draft_with_media(db_session: Session) -> None:
    project_id = _project(db_session)
    _approved_media(db_session, project_id)
    topic_id = _topic(db_session, project_id)

    result = get_post_generation_service().generate_post_for_topic(db_session, topic_id)

    assert result.post.id is not None
    assert result.post.status == "draft"
    assert result.needs_media is False
    assert result.post.media_asset_id is not None


def test_generate_needs_media_without_media(db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id, cluster="худи")

    result = get_post_generation_service().generate_post_for_topic(db_session, topic_id)

    assert result.post.status == "needs_media"
    assert result.needs_media is True
    assert result.post.media_asset_id is None


def test_generate_texts_hashtags_seo(db_session: Session) -> None:
    project_id = _project(db_session)
    _approved_media(db_session, project_id)
    topic_id = _topic(db_session, project_id)

    result = get_post_generation_service().generate_post_for_topic(db_session, topic_id)
    post = result.post

    assert post.telegram_text
    assert post.vk_text
    assert post.instagram_text
    assert post.telegram_text != post.instagram_text
    assert post.hashtags
    assert post.seo_keywords == ["футболки с логотипом", "футболки на заказ"]


def test_generate_weekly_creates_three(db_session: Session) -> None:
    _project(db_session)
    request = WeeklyPostGenerationRequest(project_slug="teeon", weeks=1, posts_per_week=3)

    result = get_post_generation_service().generate_weekly_posts(db_session, request)

    assert result.generated_count == 3
    assert len(result.posts) == 3
