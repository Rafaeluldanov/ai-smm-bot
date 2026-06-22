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
    key: str = "",
    status: str = "approved",
    source_type: str = "internal",
    license_type: str | None = None,
    products: list[str] | None = None,
    categories: list[str] | None = None,
) -> int:
    tags: dict[str, list[str]] = {"products": products or ["футболка"]}
    if categories is not None:
        tags["categories"] = categories
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="img.jpg",
            yandex_disk_path=f"disk:/{key}-{status}-{source_type}-{license_type}-{categories}.jpg",
            source_type=source_type,
            license_type=license_type,
            status=status,
            tags=tags,
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


def test_internal_beats_external_stock_even_if_older(db_session: Session) -> None:
    project_id = _project(db_session)
    # Внешний сток создан РАНЬШЕ (меньший id), но всё равно не должен выигрывать.
    external_id = _asset(
        db_session,
        project_id,
        source_type="external_stock",
        license_type="commercial_use_allowed",
    )
    internal_id = _asset(
        db_session, project_id, source_type="internal", license_type="company_owned"
    )
    selected, _ = PostMediaSelectionService().select_media_for_topic(db_session, _topic(project_id))
    assert selected is not None
    assert selected.id == internal_id
    assert selected.id != external_id


def test_external_reference_not_selected_when_internal_present(db_session: Session) -> None:
    project_id = _project(db_session)
    reference_id = _asset(
        db_session,
        project_id,
        source_type="internal",
        license_type="company_owned",
        categories=["external_reference"],
    )
    internal_id = _asset(
        db_session, project_id, source_type="internal", license_type="company_owned"
    )
    selected, _ = PostMediaSelectionService().select_media_for_topic(db_session, _topic(project_id))
    assert selected is not None
    assert selected.id == internal_id
    assert selected.id != reference_id


def test_external_stock_used_as_fallback_when_no_internal(db_session: Session) -> None:
    project_id = _project(db_session)
    external_id = _asset(
        db_session,
        project_id,
        source_type="external_stock",
        license_type="commercial_use_allowed",
    )
    selected, warnings = PostMediaSelectionService().select_media_for_topic(
        db_session, _topic(project_id)
    )
    assert selected is not None
    assert selected.id == external_id
    assert any("fallback" in w.lower() for w in warnings)


def test_exclude_forces_other_media(db_session: Session) -> None:
    project_id = _project(db_session)
    first = _asset(
        db_session, project_id, key="a", source_type="internal", license_type="company_owned"
    )
    second = _asset(
        db_session, project_id, key="b", source_type="internal", license_type="company_owned"
    )
    selected, _ = PostMediaSelectionService().select_media_for_topic(
        db_session, _topic(project_id), exclude_media_asset_ids={first}
    )
    assert selected is not None
    assert selected.id == second


def test_reuses_best_when_all_excluded(db_session: Session) -> None:
    project_id = _project(db_session)
    only = _asset(db_session, project_id, source_type="internal", license_type="company_owned")
    selected, warnings = PostMediaSelectionService().select_media_for_topic(
        db_session, _topic(project_id), exclude_media_asset_ids={only}
    )
    assert selected is not None
    assert selected.id == only  # переиспользуем лучший, раз других нет
    assert any("переиспольз" in w.lower() for w in warnings)
