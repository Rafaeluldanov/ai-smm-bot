"""Тесты репозитория медиа-активов."""

from sqlalchemy.orm import Session

from app.integrations.yandex_disk.client import YandexDiskResource
from app.repositories import media_asset_repository as repo
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def test_create_and_get_by_path(db_session: Session) -> None:
    project_id = _project(db_session)
    asset = repo.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project_id, file_name="a.jpg", yandex_disk_path="disk:/x/a.jpg"
        ),
    )
    assert asset.id is not None

    found = repo.get_media_asset_by_path(db_session, "disk:/x/a.jpg")
    assert found is not None
    assert found.id == asset.id


def test_upsert_does_not_duplicate(db_session: Session) -> None:
    project_id = _project(db_session)
    resource = YandexDiskResource(name="a.jpg", path="disk:/x/a.jpg", type="file")

    asset1, action1 = repo.upsert_media_asset_from_disk_resource(
        db_session,
        project_id=project_id,
        resource=resource,
        tags={},
        source_type="internal",
        license_type="company_owned",
        status="new",
    )
    asset2, action2 = repo.upsert_media_asset_from_disk_resource(
        db_session,
        project_id=project_id,
        resource=resource,
        tags={},
        source_type="internal",
        license_type="company_owned",
        status="new",
    )

    assert action1 == "created"
    assert action2 == "unchanged"
    assert asset1.id == asset2.id
    assert len(repo.list_media_assets(db_session, project_id=project_id)) == 1


def test_list_filters_by_project_and_status(db_session: Session) -> None:
    project_id = _project(db_session)
    repo.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project_id, file_name="n.jpg", yandex_disk_path="disk:/n.jpg", status="new"
        ),
    )
    repo.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project_id,
            file_name="a.jpg",
            yandex_disk_path="disk:/a.jpg",
            status="approved",
        ),
    )

    assert len(repo.list_media_assets(db_session, project_id=project_id)) == 2
    assert len(repo.list_media_assets(db_session, project_id=project_id, status="approved")) == 1
    assert len(repo.list_media_assets(db_session, project_id=999)) == 0
