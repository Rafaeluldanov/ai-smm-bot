"""Тесты сервиса выбора тем и контент-плана."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import media_asset_repository, topic_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services import topic_taxonomy
from app.services.market_signal_provider import StaticMarketSignalProvider
from app.services.media_analysis_service import MediaAnalysisService
from app.services.media_status_service import MediaStatusService
from app.services.media_tagging_service import MediaTaggingService
from app.services.topic_selection_service import TopicSelectionService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def _service() -> TopicSelectionService:
    return TopicSelectionService(
        market_provider=StaticMarketSignalProvider(),
        media_analysis_service=MediaAnalysisService(
            tagging_service=MediaTaggingService(),
            status_service=MediaStatusService(),
        ),
    )


def _teeon(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _candidate(cluster: str) -> dict:
    return next(
        c for c in topic_taxonomy.get_all_topic_candidates("teeon") if c["cluster"] == cluster
    )


def test_select_creates_and_saves_topics(db_session: Session) -> None:
    project_id = _teeon(db_session)
    result = _service().select_topics_for_project(db_session, project_id)

    assert result.selected_count > 0
    assert result.created > 0
    saved = topic_repository.list_topics(db_session, project_id=project_id, status="recommended")
    assert len(saved) == result.selected_count


def test_select_is_idempotent(db_session: Session) -> None:
    project_id = _teeon(db_session)
    service = _service()
    first = service.select_topics_for_project(db_session, project_id)
    second = service.select_topics_for_project(db_session, project_id)

    assert first.created > 0
    assert second.created == 0
    # Число тем не выросло (нет дублей).
    assert (
        len(topic_repository.list_topics(db_session, project_id=project_id)) == first.selected_count
    )


def test_business_priority_boosts_score() -> None:
    service = _service()
    candidate = _candidate("жаккард")
    ctx = {"readiness_by_tag": {}, "total_assets": 0, "approved_count": 0}

    without = service.score_topic_candidate("teeon", candidate, ctx, None)
    with_priority = service.score_topic_candidate("teeon", candidate, ctx, {"жаккард": 100})

    assert with_priority["priority_score"] > without["priority_score"]
    assert with_priority["business_priority"] == 100


def test_media_readiness_from_context() -> None:
    service = _service()
    candidate = _candidate("футболки")

    ready = service.score_topic_candidate(
        "teeon", candidate, {"readiness_by_tag": {"футболка": 1.0}, "approved_count": 1}, None
    )
    not_ready = service.score_topic_candidate(
        "teeon", candidate, {"readiness_by_tag": {}, "approved_count": 0}, None
    )

    assert ready["media_readiness_score"] == 1.0
    assert not_ready["media_readiness_score"] == 0.0
    assert ready["priority_score"] > not_ready["priority_score"]


def test_approved_media_raises_readiness_via_select(db_session: Session) -> None:
    project_id = _teeon(db_session)
    media_asset_repository.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project_id,
            file_name="Футболка.jpg",
            yandex_disk_path="disk:/f.jpg",
            status="approved",
            tags={"products": ["футболка"]},
        ),
    )
    result = _service().select_topics_for_project(db_session, project_id)
    tshirt_topics = [t for t in result.topics if t.cluster == "футболки"]
    assert tshirt_topics
    assert any(t.media_readiness_score == 1.0 for t in tshirt_topics)


def test_weekly_plan_three_items_with_days(db_session: Session) -> None:
    project_id = _teeon(db_session)
    plan = _service().build_weekly_content_plan(db_session, project_id)

    assert len(plan.items) == 3
    days = [item.suggested_day for item in plan.items]
    assert days == ["Понедельник", "Среда", "Пятница"]
    assert all(item.explanation for item in plan.items)


def test_weekly_plan_needs_media_when_no_media(db_session: Session) -> None:
    project_id = _teeon(db_session)
    plan = _service().build_weekly_content_plan(db_session, project_id)
    # Медиа нет вовсе -> каждый слот помечен needs_media с подсказкой.
    assert all(item.needs_media for item in plan.items)
    assert all(item.suggested_media_query for item in plan.items)


def test_no_business_priorities_warning(db_session: Session) -> None:
    project_id = _teeon(db_session)
    result = _service().select_topics_for_project(db_session, project_id)
    assert any("business_priorities" in w for w in result.warnings)


def test_unknown_project_raises(db_session: Session) -> None:
    with pytest.raises(ProjectNotFoundError):
        _service().select_topics_for_project(db_session, 99999)
