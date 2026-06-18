"""Тесты сервиса поиска внешних изображений."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import external_image_repository, media_asset_repository, post_repository
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import create_topic
from app.schemas.external_image import (
    ExternalImageConvertRequest,
    ExternalImageReviewRequest,
    ExternalImageSearchRequest,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate
from app.services.external_image_provider import FakeExternalImageProvider
from app.services.external_image_provider_registry import ExternalImageProviderRegistry
from app.services.external_image_search_service import (
    ExternalImageConversionError,
    ExternalImageSearchService,
)
from app.services.media_tagging_service import MediaTaggingService


def _service() -> ExternalImageSearchService:
    registry = ExternalImageProviderRegistry({"fake": FakeExternalImageProvider()})
    return ExternalImageSearchService(registry=registry, tagging_service=MediaTaggingService())


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _topic(db: Session, project_id: int) -> int:
    return create_topic(
        db,
        TopicCreate(project_id=project_id, title="Шелкография на футболках", cluster="шелкография"),
    ).id


def _post(db: Session, project_id: int, topic_id: int) -> int:
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id, topic_id=topic_id, title="Шелкография", status="needs_media"
        ),
    ).id


def test_search_by_project_slug_filters(db_session: Session) -> None:
    _project(db_session)
    result = _service().search_images(
        db_session, ExternalImageSearchRequest(project_slug="teeon", query="шелкография")
    )
    assert result.found_count == 4
    assert result.created == 2
    assert len(result.candidates) == 2
    assert all(c.commercial_use_allowed for c in result.candidates)
    assert all(not c.contains_logo for c in result.candidates)


def test_review_status_auto_assigned(db_session: Session) -> None:
    _project(db_session)
    result = _service().search_images(
        db_session, ExternalImageSearchRequest(project_slug="teeon", query="шелкография")
    )
    assert {c.review_status for c in result.candidates} == {"approved", "needs_review"}


def test_tags_generated(db_session: Session) -> None:
    _project(db_session)
    result = _service().search_images(
        db_session, ExternalImageSearchRequest(project_slug="teeon", query="шелкография")
    )
    assert any("шелкография" in c.tags.get("technologies", []) for c in result.candidates)


def test_search_for_post_and_topic_links(db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _post(db_session, project_id, topic_id)

    by_post = _service().search_for_post(db_session, post_id)
    assert by_post.candidates
    assert all(c.post_id == post_id for c in by_post.candidates)

    by_topic = _service().search_for_topic(db_session, topic_id)
    assert all(c.topic_id == topic_id for c in by_topic.candidates)


def test_convert_to_media_asset(db_session: Session) -> None:
    _project(db_session)
    result = _service().search_images(
        db_session, ExternalImageSearchRequest(project_slug="teeon", query="шелкография")
    )
    approved = next(c for c in result.candidates if c.review_status == "approved")

    convert = _service().convert_candidate_to_media_asset(
        db_session, approved.id, ExternalImageConvertRequest()
    )
    assert convert.media_asset_id
    asset = media_asset_repository.get_media_asset_by_id(db_session, convert.media_asset_id)
    assert asset is not None
    assert asset.source_type == "external_stock"
    assert asset.license_type != "company_owned"

    candidate = external_image_repository.get_candidate_by_id(db_session, approved.id)
    assert candidate is not None
    assert candidate.media_asset_id == convert.media_asset_id
    assert candidate.review_status == "converted_to_media_asset"
    assert any("кейс" in w for w in convert.warnings)


def test_rejected_cannot_convert(db_session: Session) -> None:
    _project(db_session)
    result = _service().search_images(
        db_session, ExternalImageSearchRequest(project_slug="teeon", query="шелкография")
    )
    candidate = result.candidates[0]
    _service().review_candidate(
        db_session, candidate.id, ExternalImageReviewRequest(review_status="rejected")
    )
    with pytest.raises(ExternalImageConversionError):
        _service().convert_candidate_to_media_asset(
            db_session, candidate.id, ExternalImageConvertRequest()
        )
