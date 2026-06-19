"""Тесты репозитория производных вариантов медиа (MediaAssetVariant)."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import media_asset_variant_repository as repo
from app.repositories.media_asset_repository import create_media_asset
from app.repositories.media_asset_variant_repository import MediaAssetVariantNotFoundError
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.media_enhancement import MediaAssetVariantCreate, MediaAssetVariantUpdate
from app.schemas.project import ProjectCreate


def _seed(db: Session) -> tuple[int, int]:
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    media = create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project.id,
            file_name="a.jpg",
            yandex_disk_path="public://yandex/teeon/SMM/Тион/a.jpg",
        ),
    )
    return project.id, media.id


def test_create_and_get(db_session: Session) -> None:
    project_id, media_id = _seed(db_session)
    variant = repo.create_variant(
        db_session,
        MediaAssetVariantCreate(
            media_asset_id=media_id, project_id=project_id, operations=["resize"]
        ),
    )
    assert variant.id is not None
    fetched = repo.get_variant_by_id(db_session, variant.id)
    assert fetched is not None
    assert fetched.operations == ["resize"]


def test_list_filters(db_session: Session) -> None:
    project_id, media_id = _seed(db_session)
    repo.create_variant(
        db_session,
        MediaAssetVariantCreate(
            media_asset_id=media_id, project_id=project_id, variant_type="enhanced"
        ),
    )
    repo.create_variant(
        db_session,
        MediaAssetVariantCreate(
            media_asset_id=media_id,
            project_id=project_id,
            variant_type="social_preview",
            status="needs_review",
        ),
    )
    assert len(repo.list_variants(db_session, project_id=project_id)) == 2
    assert len(repo.list_variants(db_session, variant_type="enhanced")) == 1
    assert len(repo.list_variants(db_session, status="needs_review")) == 1


def test_latest_variant(db_session: Session) -> None:
    project_id, media_id = _seed(db_session)
    first = repo.create_variant(
        db_session, MediaAssetVariantCreate(media_asset_id=media_id, project_id=project_id)
    )
    second = repo.create_variant(
        db_session, MediaAssetVariantCreate(media_asset_id=media_id, project_id=project_id)
    )
    latest = repo.get_latest_variant_for_media(db_session, media_id, "enhanced")
    assert latest is not None
    assert latest.id == second.id
    assert latest.id != first.id


def test_update_and_status(db_session: Session) -> None:
    project_id, media_id = _seed(db_session)
    variant = repo.create_variant(
        db_session, MediaAssetVariantCreate(media_asset_id=media_id, project_id=project_id)
    )
    updated = repo.update_variant(
        db_session, variant, MediaAssetVariantUpdate(quality_score=0.9, width=800)
    )
    assert updated.quality_score == 0.9
    assert updated.width == 800

    marked = repo.mark_variant_status(db_session, variant.id, "approved")
    assert marked.status == "approved"

    with pytest.raises(MediaAssetVariantNotFoundError):
        repo.mark_variant_status(db_session, 999, "approved")


def test_count_and_summary(db_session: Session) -> None:
    project_id, media_id = _seed(db_session)
    repo.create_variant(
        db_session, MediaAssetVariantCreate(media_asset_id=media_id, project_id=project_id)
    )
    repo.create_variant(
        db_session,
        MediaAssetVariantCreate(
            media_asset_id=media_id, project_id=project_id, status="needs_review"
        ),
    )
    assert repo.count_variants_by_project(db_session, project_id) == 2

    total, by_status, by_type = repo.summarize_variants(db_session, project_id)
    assert total == 2
    assert by_status == {"created": 1, "needs_review": 1}
    assert by_type == {"enhanced": 2}
