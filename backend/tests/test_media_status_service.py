"""Тесты сервиса статусов медиа и переходов."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import media_asset_repository as repo
from app.repositories.media_asset_repository import MediaAssetNotFoundError
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_status_service import (
    InvalidMediaStatusError,
    InvalidMediaStatusTransitionError,
    MediaStatusService,
)


def _asset(db: Session, status: str = "new") -> int:
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    asset = repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project.id, file_name="a.jpg", yandex_disk_path="disk:/a.jpg", status=status
        ),
    )
    return asset.id


def test_allowed_statuses() -> None:
    statuses = MediaStatusService().get_allowed_statuses()
    assert "needs_reshoot" in statuses
    assert "used" in statuses
    assert "rejected" in statuses


def test_valid_transitions() -> None:
    service = MediaStatusService()
    assert service.can_transition("new", "approved") is True
    assert service.can_transition("approved", "used") is True


def test_invalid_transition() -> None:
    assert MediaStatusService().can_transition("needs_license_review", "used") is False


def test_validate_transition_raises_on_forbidden() -> None:
    with pytest.raises(InvalidMediaStatusTransitionError):
        MediaStatusService().validate_transition("needs_license_review", "used")


def test_validate_transition_raises_on_unknown() -> None:
    with pytest.raises(InvalidMediaStatusError):
        MediaStatusService().validate_transition("new", "totally-unknown")


def test_update_media_status_changes_asset(db_session: Session) -> None:
    asset_id = _asset(db_session, status="new")
    updated = MediaStatusService().update_media_status(db_session, asset_id, "approved")
    assert updated.status == "approved"


def test_update_media_status_unknown_status_raises(db_session: Session) -> None:
    asset_id = _asset(db_session)
    with pytest.raises(InvalidMediaStatusError):
        MediaStatusService().update_media_status(db_session, asset_id, "bogus")


def test_update_media_status_forbidden_transition_raises(db_session: Session) -> None:
    asset_id = _asset(db_session, status="needs_license_review")
    with pytest.raises(InvalidMediaStatusTransitionError):
        MediaStatusService().update_media_status(db_session, asset_id, "used")


def test_update_media_status_missing_asset_raises(db_session: Session) -> None:
    with pytest.raises(MediaAssetNotFoundError):
        MediaStatusService().update_media_status(db_session, 99999, "approved")
