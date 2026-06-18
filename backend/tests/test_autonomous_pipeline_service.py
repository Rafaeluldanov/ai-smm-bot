"""Тесты автономного pipeline."""

import pytest
from sqlalchemy.orm import Session

from app.integrations.publishing import FakePublishingClient
from app.repositories import (
    autonomous_run_repository,
    media_asset_repository,
    post_repository,
    topic_repository,
)
from app.repositories.project_repository import create_project
from app.schemas.autonomous import AutonomousModeSettings, AutonomousRunRequest
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.analytics_provider import FakeAnalyticsProvider
from app.services.analytics_service import AnalyticsService
from app.services.autonomous_pipeline_service import (
    AutonomousPipelineService,
    AutonomousValidationError,
)
from app.services.autonomous_safety_service import AutonomousSafetyService
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
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def _pipeline(publish_success: bool = True) -> AutonomousPipelineService:
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
                "telegram": FakePublishingClient("telegram", fail=not publish_success),
                "vk": FakePublishingClient("vk", fail=not publish_success),
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


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _media(db: Session, project_id: int) -> None:
    media_asset_repository.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="m.jpg",
            yandex_disk_path="disk:/m.jpg",
            status="approved",
            tags={
                "products": ["футболка", "худи", "шоппер"],
                "technologies": ["шелкография", "dtf", "вышивка"],
            },
        ),
    )


def _request(mode: str, settings: AutonomousModeSettings | None = None) -> AutonomousRunRequest:
    return AutonomousRunRequest(
        project_slug="teeon",
        mode=mode,
        posts_per_week=3,
        business_priorities={"футболки": 100},
        settings=settings,
    )


def test_dry_run_creates_no_posts(db_session: Session) -> None:
    project_id = _project(db_session)
    result = _pipeline().run_pipeline(db_session, _request("dry_run"))
    assert result.run.mode == "dry_run"
    assert len(result.steps) == 10
    assert post_repository.list_posts(db_session, project_id=project_id) == []
    assert topic_repository.list_topics(db_session, project_id=project_id) == []


def test_semi_auto_submits_for_review(db_session: Session) -> None:
    project_id = _project(db_session)
    _media(db_session, project_id)
    result = _pipeline().run_pipeline(db_session, _request("semi_auto"))
    assert result.generated_posts == 3
    assert result.submitted_for_review >= 1
    statuses = {p.status for p in post_repository.list_posts(db_session, project_id=project_id)}
    assert "needs_review" in statuses


def test_needs_media_triggers_external_search(db_session: Session) -> None:
    _project(db_session)
    result = _pipeline().run_pipeline(db_session, _request("semi_auto"))
    assert result.posts_needing_media >= 1
    assert result.external_candidates >= 1
    assert any("медиа" in w.lower() for w in result.warnings)


def test_auto_schedule_schedules_approved(db_session: Session) -> None:
    project_id = _project(db_session)
    _media(db_session, project_id)
    settings = AutonomousModeSettings(
        allow_auto_approve=True, allow_auto_schedule=True, require_human_review=False
    )
    result = _pipeline().run_pipeline(db_session, _request("auto_schedule", settings))
    assert result.scheduled_publications >= 1
    assert result.published_publications == 0


def test_auto_publish_uses_publication_service(db_session: Session) -> None:
    project_id = _project(db_session)
    _media(db_session, project_id)
    settings = AutonomousModeSettings(
        allow_auto_approve=True,
        allow_auto_schedule=True,
        allow_auto_publish=True,
        require_human_review=False,
    )
    result = _pipeline(publish_success=True).run_pipeline(
        db_session, _request("auto_publish", settings)
    )
    assert result.published_publications >= 1


def test_project_not_found(db_session: Session) -> None:
    with pytest.raises(ProjectNotFoundError):
        _pipeline().run_pipeline(
            db_session, AutonomousRunRequest(project_slug="nope", mode="dry_run")
        )


def test_invalid_mode_raises(db_session: Session) -> None:
    _project(db_session)
    with pytest.raises(AutonomousValidationError):
        _pipeline().run_pipeline(
            db_session, AutonomousRunRequest(project_slug="teeon", mode="bogus")
        )


def test_build_report_and_steps(db_session: Session) -> None:
    _project(db_session)
    service = _pipeline()
    result = service.run_pipeline(db_session, _request("semi_auto"))

    steps = autonomous_run_repository.list_steps(db_session, result.run.id)
    assert steps
    assert {s.status for s in steps} <= {"completed", "skipped", "failed"}
    assert any(s.step_name == "generate_posts" for s in steps)

    report = service.build_report(db_session, result.run.id)
    assert report.run_id == result.run.id
    assert report.next_actions
