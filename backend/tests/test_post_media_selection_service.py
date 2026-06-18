"""Тесты подбора медиа под тему поста."""

from sqlalchemy.orm import Session

from app.models.topic import Topic
from app.repositories import media_asset_repository as media_repo
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.post_media_selection_service import PostMediaSelectionService


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _topic(project_id: int) -> Topic:
    return Topic(
        project_id=project_id,
        title="Футболки с логотипом на заказ",
        cluster="футболки",
        seo_keywords=[],
    )


def _asset(
    db: Session,
    project_id: int,
    *,
    status: str = "approved",
    source_type: str = "internal",
    license_type: str | None = None,
    products: list[str] | None = None,
) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="img.jpg",
            yandex_disk_path=f"disk:/{status}-{source_type}-{license_type}.jpg",
            source_type=source_type,
            license_type=license_type,
            status=status,
            tags={"products": products or ["футболка"]},
        ),
    )
    return asset.id


def test_selects_approved_by_tags(db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, status="approved")
    selected, warnings = PostMediaSelectionService().select_media_for_topic(
        db_session, _topic(project_id)
    )
    assert selected is not None
    assert selected.id == asset_id
    assert warnings == []


def test_prefers_approved_over_new(db_session: Session) -> None:
    project_id = _project(db_session)
    _asset(db_session, project_id, status="new")
    approved_id = _asset(db_session, project_id, status="approved")
    selected, _ = PostMediaSelectionService().select_media_for_topic(db_session, _topic(project_id))
    assert selected is not None
    assert selected.id == approved_id


def test_ignores_new_rejected_reshoot(db_session: Session) -> None:
    project_id = _project(db_session)
    _asset(db_session, project_id, status="new")
    _asset(db_session, project_id, status="rejected")
    _asset(db_session, project_id, status="needs_reshoot")
    selected, warnings = PostMediaSelectionService().select_media_for_topic(
        db_session, _topic(project_id)
    )
    assert selected is None
    assert warnings


def test_ignores_external_stock_needing_license(db_session: Session) -> None:
    project_id = _project(db_session)
    _asset(
        db_session,
        project_id,
        status="approved",
        source_type="external_stock",
        license_type="external_needs_review",
    )
    selected, warnings = PostMediaSelectionService().select_media_for_topic(
        db_session, _topic(project_id)
    )
    assert selected is None
    assert warnings


def test_warning_when_no_media(db_session: Session) -> None:
    project_id = _project(db_session)
    selected, warnings = PostMediaSelectionService().select_media_for_topic(
        db_session, _topic(project_id)
    )
    assert selected is None
    assert warnings
