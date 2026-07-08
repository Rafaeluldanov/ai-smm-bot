"""Тесты маршрутизации медиа Яндекс Диска в байты для платформ (offline)."""

from pathlib import Path
from types import SimpleNamespace

from app.integrations import media_attachments as ma

_DISK_PATH = "public://yandex/teeon/teeon/file.HEIC"


class FakeDownloader:
    """Публичный загрузчик без сети (отдаёт готовые байты)."""

    def __init__(self, content: bytes = b"heic-bytes") -> None:
        self.content = content
        self.calls: list[tuple[str, str]] = []

    def download_public_media(self, disk_path: str, file_name: str) -> SimpleNamespace:
        self.calls.append((disk_path, file_name))
        return SimpleNamespace(bytes=self.content, content_type="image/heic", file_name=file_name)


class FakeImageProcessor:
    """Фейковый конвертер HEIC→JPEG (не открывает файл)."""

    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str]] = []

    def enhance_image_bytes(
        self, image_bytes: bytes, profile: str, operations: dict[str, bool] | None = None
    ) -> SimpleNamespace:
        self.calls.append((image_bytes, profile))
        return SimpleNamespace(output_bytes=b"\xff\xd8\xff\xe0converted-jpeg")


def test_public_yandex_file_routed_to_bytes_via_downloader() -> None:
    downloader = FakeDownloader(b"heic-file-bytes")
    item = {
        "id": 1,
        "file_name": "file.HEIC",
        "yandex_disk_path": _DISK_PATH,
        "media_kind": "image",
    }

    content, file_name = ma.load_item_bytes(item, downloader)

    assert content == b"heic-file-bytes"
    assert file_name == "file.HEIC"
    assert downloader.calls == [(_DISK_PATH, "file.HEIC")]


def test_original_yandex_path_preserved() -> None:
    item = {
        "id": 1,
        "file_name": "file.HEIC",
        "yandex_disk_path": _DISK_PATH,
        "media_kind": "image",
    }
    ma.load_item_bytes(item, FakeDownloader())
    # Загрузка не мутирует исходный путь диска.
    assert item["yandex_disk_path"] == _DISK_PATH


def test_heic_converted_to_jpeg_in_memory() -> None:
    processor = FakeImageProcessor()
    content, file_name, content_type = ma.maybe_convert_heic(b"heic-bytes", "file.HEIC", processor)
    assert content == b"\xff\xd8\xff\xe0converted-jpeg"
    assert file_name == "file.jpg"
    assert content_type == "image/jpeg"
    assert processor.calls and processor.calls[0][0] == b"heic-bytes"


def test_original_file_on_disk_not_overwritten(tmp_path: Path) -> None:
    original = tmp_path / "orig.HEIC"
    original.write_bytes(b"original-heic-bytes")
    item = {"media_path": str(original), "file_name": "orig.HEIC", "media_kind": "image"}

    content, name = ma.load_item_bytes(item, None)
    # Конвертация идёт в памяти — оригинал на диске остаётся нетронутым.
    ma.maybe_convert_heic(content, name, FakeImageProcessor())

    assert original.read_bytes() == b"original-heic-bytes"


def test_non_heic_not_converted() -> None:
    processor = FakeImageProcessor()
    content, file_name, content_type = ma.maybe_convert_heic(b"jpeg", "photo.jpg", processor)
    assert content == b"jpeg"
    assert file_name == "photo.jpg"
    assert content_type == "image/jpeg"
    assert processor.calls == []  # jpg не конвертируется


def test_local_enhanced_path_read_without_downloader(tmp_path: Path) -> None:
    jpg = tmp_path / "enhanced.jpg"
    jpg.write_bytes(b"local-jpeg")
    item = {"media_path": str(jpg), "file_name": "enhanced.jpg", "media_kind": "image"}
    content, file_name = ma.load_item_bytes(item, None)
    assert content == b"local-jpeg"
    assert file_name == "enhanced.jpg"


def test_unavailable_media_returns_none() -> None:
    item = {
        "media_path": "/nonexistent/missing.jpg",
        "file_name": "missing.jpg",
        "media_kind": "image",
    }
    content, file_name = ma.load_item_bytes(item, None)
    assert content is None
    assert file_name == "missing.jpg"


def test_is_image_and_is_video() -> None:
    assert ma.is_image("photo.HEIC") is True
    assert ma.is_image("clip.MOV") is False
    assert ma.is_video("clip.mp4") is True
    assert ma.is_video("photo.jpg") is False


def test_sanitize_filename_strips_paths() -> None:
    assert ma.sanitize_filename("/a/b/photo.jpg") == "photo.jpg"
    assert ma.sanitize_filename("bad\r\nname.jpg") == "badname.jpg"
    assert ma.sanitize_filename("") == "media"
