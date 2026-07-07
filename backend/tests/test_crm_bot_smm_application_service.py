"""Тесты интеграции конфигурации «БОТ СММ» с SEO-модулями и pipeline."""

import copy
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.publishing import FakePublishingClient
from app.repositories import crm_bot_smm_repository as repo
from app.repositories import media_asset_repository, post_repository
from app.schemas.media_asset import MediaAssetCreate
from app.services.analytics_provider import FakeAnalyticsProvider
from app.services.analytics_service import AnalyticsService
from app.services.autonomous_pipeline_service import AutonomousPipelineService
from app.services.autonomous_safety_service import AutonomousSafetyService
from app.services.crm_bot_smm_application_service import CrmBotSmmApplicationService
from app.services.crm_bot_smm_form_service import CrmBotSmmFormService
from app.services.external_image_provider import FakeExternalImageProvider
from app.services.external_image_provider_registry import ExternalImageProviderRegistry
from app.services.external_image_search_service import ExternalImageSearchService
from app.services.market_signal_provider import StaticMarketSignalProvider
from app.services.media_analysis_service import MediaAnalysisService
from app.services.media_status_service import MediaStatusService
from app.services.media_tagging_service import MediaTaggingService
from app.services.post_generation_service import PostGenerationService
from app.services.post_media_selection_service import PostMediaSelectionService
from app.services.post_publication_service import PostPublicationService
from app.services.post_review_service import PostReviewService
from app.services.publication_platform_registry import PublicationPlatformRegistry
from app.services.topic_selection_service import TopicSelectionService

EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent / "examples" / "crm_bot_smm_onboarding_teeon.json"
)


def _example() -> dict[str, Any]:
    return copy.deepcopy(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))


def _fake_pipeline() -> AutonomousPipelineService:
    """Pipeline с фейковыми клиентами публикации (сеть не вызывается)."""
    media_analysis = MediaAnalysisService(
        tagging_service=MediaTaggingService(), status_service=MediaStatusService()
    )
    topic = TopicSelectionService(
        market_provider=StaticMarketSignalProvider(), media_analysis_service=media_analysis
    )
    generation = PostGenerationService(
        media_selection_service=PostMediaSelectionService(), topic_selection_service=topic
    )
    publication = PostPublicationService(
        registry=PublicationPlatformRegistry(
            {
                "telegram": FakePublishingClient("telegram"),
                "vk": FakePublishingClient("vk"),
            }
        ),
        default_targets={"telegram": "@c", "vk": "-1"},
    )
    external = ExternalImageSearchService(
        registry=ExternalImageProviderRegistry({"fake": FakeExternalImageProvider()}),
        tagging_service=MediaTaggingService(),
    )
    return AutonomousPipelineService(
        topic_selection_service=topic,
        post_generation_service=generation,
        post_review_service=PostReviewService(),
        post_publication_service=publication,
        external_image_search_service=external,
        analytics_service=AnalyticsService(provider=FakeAnalyticsProvider()),
        safety_service=AutonomousSafetyService(),
    )


def _apply_example(db: Session) -> tuple[int, int]:
    """Применить пример онбординга. Возвращает (config_id, category_id)."""
    preview = CrmBotSmmFormService().apply_onboarding_payload(db, _example(), dry_run=False)
    assert preview.config_id is not None
    category = repo.list_categories_by_config(db, preview.config_id)[0]
    return preview.config_id, category.id


def _seed_media(db: Session, project_id: int) -> None:
    media_asset_repository.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="m.jpg",
            yandex_disk_path="disk:/m.jpg",
            status="approved",
            tags={
                "products": ["футболка", "худи"],
                "technologies": ["dtf", "вышивка"],
            },
        ),
    )


def test_content_plan_30_items_with_site_url_and_category_keys(db_session: Session) -> None:
    _config_id, category_id = _apply_example(db_session)
    plan = CrmBotSmmApplicationService().build_content_plan_from_category(
        db_session, category_id, days=30
    )
    assert len(plan.items) == 30
    assert all(item.site_url for item in plan.items)
    assert all("teeon.ru" in item.site_url for item in plan.items)

    keyword_queries = set(_example()["promotion_categories"][0]["keyword_queries"])
    plan_queries = {item.seo_query for item in plan.items}
    assert plan_queries & keyword_queries


def test_run_dry_creates_no_posts(db_session: Session) -> None:
    _config_id, category_id = _apply_example(db_session)
    service = CrmBotSmmApplicationService(pipeline_service=_fake_pipeline())
    result = service.run_category_semi_auto(db_session, category_id, dry_run=True)
    assert result.dry_run is True
    assert result.published_publications == 0
    posts = post_repository.list_posts(db_session, project_id=None)
    assert posts == []


def test_run_semi_auto_creates_needs_review_without_publishing(db_session: Session) -> None:
    config_id, category_id = _apply_example(db_session)
    config = repo.get_config_by_id(db_session, config_id)
    assert config is not None
    _seed_media(db_session, config.project_id)

    service = CrmBotSmmApplicationService(pipeline_service=_fake_pipeline())
    result = service.run_category_semi_auto(db_session, category_id, dry_run=False)

    assert result.published_publications == 0
    assert result.generated_posts >= 1
    posts = post_repository.list_posts(db_session, project_id=config.project_id)
    assert "needs_review" in {p.status for p in posts}
    # Публикаций не создано ни одной.
    for post in posts:
        assert post.status != "published"


def test_build_seo_profile_preset_teeon(db_session: Session) -> None:
    config_id, _category_id = _apply_example(db_session)
    profile = CrmBotSmmApplicationService().build_seo_profile_from_config(db_session, config_id)
    assert profile.project_slug == "teeon"
    assert profile.site_url == "https://teeon.ru"
    assert profile.seo_queries  # preset содержит seed-ядро


def test_build_seo_profile_temporary_for_new_project(db_session: Session) -> None:
    payload = _example()
    payload["project"]["slug"] = "new-client"
    payload["project"]["display_name"] = "Новый клиент"
    payload["site_or_topics"]["has_website"] = False
    payload["site_or_topics"]["website_url"] = None
    payload["site_or_topics"]["manual_topics"] = ["кружки", "ручки"]
    preview = CrmBotSmmFormService().apply_onboarding_payload(db_session, payload, dry_run=False)
    assert preview.config_id is not None
    profile = CrmBotSmmApplicationService().build_seo_profile_from_config(
        db_session, preview.config_id
    )
    assert profile.project_slug == "new-client"
    assert profile.brand_name == "Новый клиент"
