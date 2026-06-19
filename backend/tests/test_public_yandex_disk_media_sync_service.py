"""Тесты сервиса публичной синхронизации медиа (без сети)."""

from sqlalchemy.orm import Session

from app.integrations.yandex_disk.client import YandexDiskPublicResource
from app.repositories import media_asset_repository
from app.repositories.project_repository import create_project
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
