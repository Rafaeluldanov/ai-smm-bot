"""Тесты сервиса синхронизации медиа с Яндекс Диска (клиент замокан)."""

from collections.abc import Iterable

import pytest
from sqlalchemy.orm import Session

from app.integrations.yandex_disk.client import YandexDiskNotFoundError, YandexDiskResource
from app.repositories import media_asset_repository as media_repo
from app.repositories.project_repository import create_project
from app.schemas.project import ProjectCreate
from app.services.media_tagging_service import MediaTaggingService
from app.services.project_media_paths import get_default_scan_folders
from app.services.yandex_disk_media_sync_service import (
    ProjectNotFoundError,
    YandexDiskMediaSyncService,
)


class FakeClient:
    """Поддельный клиент: возвращает заранее заданные файлы по папкам."""

    def __init__(
        self,
        files_by_folder: dict[str, list[YandexDiskResource]],
        missing: Iterable[str] = (),
    ) -> None:
        self._files = files_by_folder
        self._missing = set(missing)

    def list_files_recursive(self, path: str, max_depth: int = 3) -> list[YandexDiskResource]:
        if path in self._missing:
            raise YandexDiskNotFoundError(path)
        return list(self._files.get(path, []))


def _file(folder: str, name: str) -> YandexDiskResource:
    return YandexDiskResource(name=name, path=f"{folder}/{name}", type="file")


def _service(client: FakeClient) -> YandexDiskMediaSyncService:
    return YandexDiskMediaSyncService(client=client, tagging_service=MediaTaggingService())


def _seed_teeon(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def test_sync_creates_media_assets(db_session: Session) -> None:
    project_id = _seed_teeon(db_session)
    incoming, approved, _video, external, _reshoot = get_default_scan_folders("teeon")
    files = {
        incoming: [_file(incoming, "Худи с карманом с шелкографией и жаккардами.jpg")],
        approved: [_file(approved, "Поло с вышивкой.jpg")],
        external: [_file(external, "external-stock.jpg")],
    }

    result = _service(FakeClient(files)).sync_project_media_by_slug(db_session, "teeon")

    assert result.found_files == 3
    assert result.created == 3
    assert len(media_repo.list_media_assets(db_session, project_id=project_id)) == 3


def test_sync_is_idempotent(db_session: Session) -> None:
    _seed_teeon(db_session)
    incoming = get_default_scan_folders("teeon")[0]
    service = _service(FakeClient({incoming: [_file(incoming, "Футболка.jpg")]}))

    first = service.sync_project_media_by_slug(db_session, "teeon")
    second = service.sync_project_media_by_slug(db_session, "teeon")

    assert first.created == 1
    assert second.created == 0
    assert second.skipped == 1
    assert len(media_repo.list_media_assets(db_session)) == 1


def test_sync_parses_tags_from_file_name(db_session: Session) -> None:
    _seed_teeon(db_session)
    incoming = get_default_scan_folders("teeon")[0]
    name = "Худи с карманом с шелкографией и жаккардами.jpg"
    _service(FakeClient({incoming: [_file(incoming, name)]})).sync_project_media_by_slug(
        db_session, "teeon"
    )

    asset = media_repo.list_media_assets(db_session)[0]
    assert asset.tags["products"] == ["худи"]
    assert asset.tags["technologies"] == ["шелкография"]
    assert "карман" in asset.tags["details"]
    assert "жаккард" in asset.tags["details"]


def test_external_folder_classification(db_session: Session) -> None:
    _seed_teeon(db_session)
    external = get_default_scan_folders("teeon")[3]
    _service(
        FakeClient({external: [_file(external, "stock-photo.jpg")]})
    ).sync_project_media_by_slug(db_session, "teeon")

    asset = media_repo.list_media_assets(db_session)[0]
    assert asset.source_type == "external_stock"
    assert asset.status == "needs_license_review"


def test_missing_folder_does_not_abort_sync(db_session: Session) -> None:
    _seed_teeon(db_session)
    folders = get_default_scan_folders("teeon")
    incoming, _approved, video, _external, _reshoot = folders
    client = FakeClient({incoming: [_file(incoming, "Кружка.jpg")]}, missing={video})

    result = _service(client).sync_project_media_by_slug(db_session, "teeon")

    assert result.created == 1
    assert len(result.errors) == 1
    assert "не найдена" in result.errors[0].lower()


def test_reshoot_folder_status(db_session: Session) -> None:
    _seed_teeon(db_session)
    reshoot = get_default_scan_folders("teeon")[4]
    assert "06_Нужно_переснять" in reshoot
    _service(
        FakeClient({reshoot: [_file(reshoot, "Старое фото футболки.jpg")]})
    ).sync_project_media_by_slug(db_session, "teeon")

    asset = media_repo.list_media_assets(db_session)[0]
    assert asset.status == "needs_reshoot"
    assert asset.source_type == "internal"


def test_sync_stores_rich_tags(db_session: Session) -> None:
    _seed_teeon(db_session)
    incoming = get_default_scan_folders("teeon")[0]
    name = "Худи с карманом с шелкографией и жаккардами.jpg"
    _service(FakeClient({incoming: [_file(incoming, name)]})).sync_project_media_by_slug(
        db_session, "teeon"
    )

    tags = media_repo.list_media_assets(db_session)[0].tags
    # Расширенная структура тегов сохранена.
    for key in ("products", "technologies", "details", "categories", "topics", "confidence"):
        assert key in tags


def test_sync_unknown_project_raises(db_session: Session) -> None:
    with pytest.raises(ProjectNotFoundError):
        _service(FakeClient({})).sync_project_media_by_slug(db_session, "does-not-exist")
