"""Тесты сервиса публичной синхронизации медиа (без сети)."""

from sqlalchemy.orm import Session

from app.integrations.yandex_disk.client import (
    YandexDiskError,
    YandexDiskPublicClient,
    YandexDiskPublicResource,
)
from app.repositories import media_asset_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_tagging_service import MediaTaggingService
from app.services.public_yandex_disk_media_sync_service import PublicYandexDiskMediaSyncService


def _dir(name: str, path: str) -> YandexDiskPublicResource:
    return YandexDiskPublicResource(name=name, path=path, type="dir")


def _file(name: str, path: str, media_type: str = "image") -> YandexDiskPublicResource:
    return YandexDiskPublicResource(name=name, path=path, type="file", media_type=media_type)


def _tree() -> dict[str, list[YandexDiskPublicResource]]:
    return {
        "/SMM": [_dir("Тион", "/SMM/Тион"), _dir("Фабрика сувениров", "/SMM/Фабрика сувениров")],
        "/SMM/Тион": [
            _file(
                "futbolki-logotip-shelkografiya.jpg", "/SMM/Тион/futbolki-logotip-shelkografiya.jpg"
            ),
            _file("hoodie-dtf-merch.mp4", "/SMM/Тион/hoodie-dtf-merch.mp4", "video"),
            _file("notes.txt", "/SMM/Тион/notes.txt", "document"),
        ],
        "/SMM/Фабрика сувениров": [
            _file("kruzhki-uf-pechat.jpg", "/SMM/Фабрика сувениров/kruzhki-uf-pechat.jpg"),
        ],
    }


class _FakePublicClient:
    def __init__(self, tree: dict[str, list[YandexDiskPublicResource]]) -> None:
        self._tree = tree

    def list_public_resources(self, public_key, path=None, limit=100, offset=0):
        return list(self._tree.get(path or "/", []))

    def list_public_files_recursive(self, public_key, path=None, max_depth=5):
        files: list[YandexDiskPublicResource] = []

        def walk(current: str) -> None:
            for resource in self._tree.get(current, []):
                if resource.is_file:
                    files.append(resource)
                elif resource.is_dir:
                    walk(resource.path)

        walk(path or "/")
        return files

    def get_public_download_url(self, public_key, path=None):
        return "https://dl/x"


def _service() -> PublicYandexDiskMediaSyncService:
    return PublicYandexDiskMediaSyncService(
        client=_FakePublicClient(_tree()),
        tagging_service=MediaTaggingService(),
        public_key="https://disk.yandex.ru/d/X",
        root_folder="SMM",
    )


def _project(db: Session, slug: str) -> int:
    return create_project(db, ProjectCreate(name=slug, slug=slug)).id


def test_teeon_only_from_tion(db_session: Session) -> None:
    project_id = _project(db_session, "teeon")
    result = _service().sync_project_media_by_slug_from_public_link(db_session, "teeon")
    assert result.created == 2
    assets = media_asset_repository.list_media_assets(db_session, project_id=project_id)
    paths = [a.yandex_disk_path or "" for a in assets]
    assert all("Тион" in p for p in paths)
    assert not any("Фабрика" in p for p in paths)
    assert all("Фабрика" not in folder for folder in result.scanned_folders)


def test_fabric_from_both_folders(db_session: Session) -> None:
    _project(db_session, "fabric-souvenirs")
    result = _service().sync_project_media_by_slug_from_public_link(db_session, "fabric-souvenirs")
    assert result.created == 3
    assert any("Тион" in folder for folder in result.scanned_folders)
    assert any("Фабрика" in folder for folder in result.scanned_folders)


def test_tags_extracted(db_session: Session) -> None:
    project_id = _project(db_session, "teeon")
    _service().sync_project_media_by_slug_from_public_link(db_session, "teeon")
    assets = media_asset_repository.list_media_assets(db_session, project_id=project_id)
    hoodie = next(a for a in assets if "hoodie" in a.file_name)
    assert "dtf" in hoodie.tags.get("technologies", [])


def test_non_media_ignored(db_session: Session) -> None:
    project_id = _project(db_session, "teeon")
    _service().sync_project_media_by_slug_from_public_link(db_session, "teeon")
    assets = media_asset_repository.list_media_assets(db_session, project_id=project_id)
    assert not any(a.file_name == "notes.txt" for a in assets)


def test_repeated_sync_no_duplicate(db_session: Session) -> None:
    project_id = _project(db_session, "teeon")
    service = _service()
    service.sync_project_media_by_slug_from_public_link(db_session, "teeon")
    service.sync_project_media_by_slug_from_public_link(db_session, "teeon")
    assets = media_asset_repository.list_media_assets(db_session, project_id=project_id)
    assert len(assets) == 2


def test_teeon_ignores_fabric_nested_under_tion(db_session: Session) -> None:
    # «Фабрика сувениров» ВЛОЖЕНА в «Тион» — teeon не должен брать её медиа.
    project_id = _project(db_session, "teeon")
    tree = {
        "/SMM": [_dir("Тион", "/SMM/Тион")],
        "/SMM/Тион": [
            _file("tion-foto.jpg", "/SMM/Тион/tion-foto.jpg"),
            _dir("Фабрика сувениров", "/SMM/Тион/Фабрика сувениров"),
        ],
        "/SMM/Тион/Фабрика сувениров": [
            _file("kruzhki-uf-pechat.jpg", "/SMM/Тион/Фабрика сувениров/kruzhki-uf-pechat.jpg"),
        ],
    }
    service = PublicYandexDiskMediaSyncService(
        client=_FakePublicClient(tree),
        tagging_service=MediaTaggingService(),
        public_key="https://disk.yandex.ru/d/X",
        root_folder="SMM",
    )
    service.sync_project_media_by_slug_from_public_link(db_session, "teeon")
    assets = media_asset_repository.list_media_assets(db_session, project_id=project_id)
    assert any("tion-foto" in a.file_name for a in assets)
    assert not any("kruzhki" in a.file_name for a in assets)
    assert not any("Фабрика" in (a.yandex_disk_path or "") for a in assets)


def test_two_projects_get_separate_tion_assets(db_session: Session) -> None:
    # Оба проекта сканируют общую «Тион»: у каждого свой MediaAsset, без коллизий.
    teeon_id = _project(db_session, "teeon")
    fabric_id = _project(db_session, "fabric-souvenirs")
    service = _service()
    service.sync_project_media_by_slug_from_public_link(db_session, "teeon")
    service.sync_project_media_by_slug_from_public_link(db_session, "fabric-souvenirs")

    teeon_assets = media_asset_repository.list_media_assets(db_session, project_id=teeon_id)
    fabric_assets = media_asset_repository.list_media_assets(db_session, project_id=fabric_id)
    assert len(teeon_assets) == 2  # только «Тион»
    assert len(fabric_assets) == 3  # «Тион» (2) + «Фабрика» (1)
    teeon_paths = {a.yandex_disk_path for a in teeon_assets}
    fabric_paths = {a.yandex_disk_path for a in fabric_assets}
    assert teeon_paths.isdisjoint(fabric_paths)  # ни одной общей строки


class _PaginatingPublicClient(YandexDiskPublicClient):
    """Реальный клиент, но листинг берётся из in-memory дерева (без сети).

    Переопределяет только ``list_public_resources`` (с пагинацией по offset/limit) —
    унаследованные ``list_all_public_resources`` / ``list_public_files_recursive`` /
    ``find_public_resource_by_path`` работают поверх него.
    """

    def __init__(self, tree: dict[str, list[YandexDiskPublicResource]]) -> None:
        super().__init__(base_url="https://disk.example/v1/disk")
        self._tree = tree

    def list_public_resources(self, public_key, path=None, limit=100, offset=0):
        items = list(self._tree.get(path or "/", []))
        return items[offset : offset + limit]


def test_sync_paginates_large_folder(db_session: Session) -> None:
    # В «Тион» 150 файлов (две страницы) — sync должен увидеть все 150, не 100.
    project_id = _project(db_session, "teeon")
    tree = {
        "/SMM": [_dir("Тион", "/SMM/Тион")],
        "/SMM/Тион": [_file(f"img-{i}.jpg", f"/SMM/Тион/img-{i}.jpg") for i in range(150)],
    }
    service = PublicYandexDiskMediaSyncService(
        client=_PaginatingPublicClient(tree),
        tagging_service=MediaTaggingService(),
        public_key="https://disk.yandex.ru/d/X",
        root_folder="SMM",
    )
    result = service.sync_project_media_by_slug_from_public_link(db_session, "teeon")

    assert result.found_files == 150
    assert result.created == 150
    # list_media_assets ограничен limit=100 — берём полный список без пагинации.
    assets = media_asset_repository.list_media_assets_by_project(db_session, project_id)
    assert len(assets) == 150
    # access policy не ослаблена — всё из «Тион».
    assert all("Тион" in (a.yandex_disk_path or "") for a in assets)


def test_stale_public_media_warning_keeps_records(db_session: Session) -> None:
    project_id = _project(db_session, "teeon")
    # Старый MediaAsset, которого больше нет на диске (файл переименовали).
    media_asset_repository.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project_id,
            file_name="old.jpg",
            yandex_disk_path="public://yandex/teeon/teeon/old.jpg",
            source_type="internal",
            status="new",
        ),
    )
    tree = {
        "/": [_dir("teeon", "/teeon")],
        "/teeon": [_file("new.jpg", "/teeon/new.jpg")],
    }
    service = PublicYandexDiskMediaSyncService(
        client=_PaginatingPublicClient(tree),
        tagging_service=MediaTaggingService(),
        public_key="https://disk.yandex.ru/d/X",
        root_folder="SMM",
    )
    result = service.sync_project_media_by_slug_from_public_link(db_session, "teeon")

    names = {
        a.file_name
        for a in media_asset_repository.list_media_assets(db_session, project_id=project_id)
    }
    assert "new.jpg" in names  # новый создан
    assert "old.jpg" in names  # старый НЕ удалён
    assert any("Stale public media not found on disk: 1" in e for e in result.errors)
    assert any("teeon/old.jpg" in e for e in result.errors)


def test_one_folder_network_error_recorded_not_fatal(db_session: Session) -> None:
    _project(db_session, "teeon")

    class _PartialFailClient:
        def list_public_resources(self, public_key, path=None, limit=100, offset=0):
            return [_dir("teeon", "/teeon")] if (path or "/") == "/" else []

        def list_public_files_recursive(self, public_key, path=None, max_depth=5):
            raise YandexDiskError("Ошибка публичного Яндекс Диска: сетевая ошибка/таймаут")

    service = PublicYandexDiskMediaSyncService(
        client=_PartialFailClient(),
        tagging_service=MediaTaggingService(),
        public_key="https://disk.yandex.ru/d/X",
        root_folder="SMM",
    )
    result = service.sync_project_media_by_slug_from_public_link(db_session, "teeon")

    assert any("Ошибка при сканировании" in e for e in result.errors)
    assert result.found_files == 0  # sync не упал, лишь записал ошибку папки


def test_stale_skipped_when_a_folder_scan_fails(db_session: Session) -> None:
    # fabric-souvenirs сканирует «Тион» И «Фабрика». Если «Тион» упала (таймаут),
    # её present-файл в БД НЕ должен помечаться stale — скан неполный.
    project_id = _project(db_session, "fabric-souvenirs")
    media_asset_repository.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project_id,
            file_name="tion-old.jpg",
            yandex_disk_path="public://yandex/fabric-souvenirs/SMM/Тион/tion-old.jpg",
            source_type="internal",
            status="new",
        ),
    )

    class _OneFolderFailsClient:
        def list_public_resources(self, public_key, path=None, limit=100, offset=0):
            tree = {
                "/SMM": [
                    _dir("Тион", "/SMM/Тион"),
                    _dir("Фабрика сувениров", "/SMM/Фабрика сувениров"),
                ],
            }
            return list(tree.get(path or "/", []))[offset : offset + limit]

        def list_public_files_recursive(self, public_key, path=None, max_depth=5):
            if "Тион" in (path or ""):
                raise YandexDiskError("сетевая ошибка/таймаут")
            return [_file("kruzhki.jpg", "/SMM/Фабрика сувениров/kruzhki.jpg")]

    service = PublicYandexDiskMediaSyncService(
        client=_OneFolderFailsClient(),
        tagging_service=MediaTaggingService(),
        public_key="https://disk.yandex.ru/d/X",
        root_folder="SMM",
    )
    result = service.sync_project_media_by_slug_from_public_link(db_session, "fabric-souvenirs")

    assert any("Ошибка при сканировании" in e for e in result.errors)
    # Ложного stale про present tion-old.jpg быть НЕ должно (скан неполный).
    assert not any("Stale public media" in e for e in result.errors)
    survivors = media_asset_repository.list_media_assets_by_project(db_session, project_id)
    assert any(a.file_name == "tion-old.jpg" for a in survivors)


def test_stale_skipped_when_all_folders_fail_with_existing_asset(db_session: Session) -> None:
    # Все папки упали (current_paths пуст), но в БД есть запись — stale не выдаём.
    project_id = _project(db_session, "teeon")
    media_asset_repository.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project_id,
            file_name="old.jpg",
            yandex_disk_path="public://yandex/teeon/teeon/old.jpg",
            source_type="internal",
            status="new",
        ),
    )

    class _AllFailClient:
        def list_public_resources(self, public_key, path=None, limit=100, offset=0):
            return [_dir("teeon", "/teeon")] if (path or "/") == "/" else []

        def list_public_files_recursive(self, public_key, path=None, max_depth=5):
            raise YandexDiskError("таймаут")

    service = PublicYandexDiskMediaSyncService(
        client=_AllFailClient(),
        tagging_service=MediaTaggingService(),
        public_key="https://disk.yandex.ru/d/X",
        root_folder="SMM",
    )
    result = service.sync_project_media_by_slug_from_public_link(db_session, "teeon")

    assert not any("Stale public media" in e for e in result.errors)
    survivors = media_asset_repository.list_media_assets_by_project(db_session, project_id)
    assert any(a.file_name == "old.jpg" for a in survivors)


def test_list_media_assets_by_path_prefix_respects_project_id(db_session: Session) -> None:
    teeon_id = _project(db_session, "teeon")
    fabric_id = _project(db_session, "fabric-souvenirs")
    media_asset_repository.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=teeon_id,
            file_name="t.jpg",
            yandex_disk_path="public://yandex/teeon/teeon/t.jpg",
            source_type="internal",
        ),
    )
    media_asset_repository.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=fabric_id,
            file_name="f.jpg",
            yandex_disk_path="public://yandex/fabric-souvenirs/teeon/f.jpg",
            source_type="internal",
        ),
    )
    # Узкий префикс по slug возвращает только свою запись.
    teeon_only = media_asset_repository.list_media_assets_by_path_prefix(
        db_session, "public://yandex/teeon/", teeon_id
    )
    assert {a.file_name for a in teeon_only} == {"t.jpg"}
    # Широкий префикс матчит обе записи, но project_id ограничивает одной.
    broad = media_asset_repository.list_media_assets_by_path_prefix(
        db_session, "public://yandex/", teeon_id
    )
    assert {a.file_name for a in broad} == {"t.jpg"}
    assert all(a.project_id == teeon_id for a in broad)
