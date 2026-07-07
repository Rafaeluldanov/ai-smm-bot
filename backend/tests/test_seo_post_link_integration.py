"""Тесты интеграции ссылки на сайт в текст поста (Задача 3)."""

from sqlalchemy.orm import Session

from app.api.deps import get_post_generation_service
from app.repositories import media_asset_repository as media_repo
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import create_topic
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate


def _setup(db: Session) -> int:
    project_id = create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id
    media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="f.jpg",
            yandex_disk_path="disk:/f.jpg",
            source_type="internal",
            license_type="company_owned",
            status="approved",
            tags={"products": ["футболка"]},
        ),
    )
    return create_topic(
        db,
        TopicCreate(
            project_id=project_id,
            title="Футболки с логотипом на заказ",
            cluster="футболки",
            seo_keywords=["пошив футболок с логотипом на заказ"],
            status="recommended",
        ),
    ).id


def test_post_texts_contain_site_link(db_session: Session) -> None:
    topic_id = _setup(db_session)
    result = get_post_generation_service().generate_post_for_topic(db_session, topic_id)
    post = result.post

    assert "https://teeon.ru/catalog/futbolki" in post.vk_text
    assert "https://teeon.ru/catalog/futbolki" in post.telegram_text
    assert "Подробнее и расчёт тиража:" in post.vk_text
    # Одна ссылка на пост — не спамим.
    assert post.vk_text.count("https://teeon.ru") == 1
    assert post.telegram_text.count("https://teeon.ru") == 1


def test_link_selection_helper_on_service(db_session: Session) -> None:
    topic_id = _setup(db_session)
    from app.repositories.topic_repository import get_topic_by_id

    topic = get_topic_by_id(db_session, topic_id)
    assert topic is not None
    link = get_post_generation_service().select_site_link_for_topic("teeon", topic)
    assert link is not None
    assert link.url == "https://teeon.ru/catalog/futbolki"
