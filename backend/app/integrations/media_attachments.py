"""Общие помощники медиа-вложений для клиентов публикации (VK/Telegram).

Чистые функции уровня модуля без бизнес-логики платформ: определение типа файла,
загрузка байтов одного медиа из группы (локальная enhanced-копия или публичная
папка Яндекс Диска) и best-effort конвертация HEIC/HEIF → JPEG в памяти.

Оригиналы на диске НЕ перезаписываются. Сеть используется только если у медиа нет
локального пути и передан загрузчик (``download_public_media``); в тестах он
подменяется fake-объектом.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

# Видео пока не загружается ни в VK, ни в Telegram — только фото.
VIDEO_EXTENSIONS: frozenset[str] = frozenset({"mov", "mp4", "m4v", "avi", "mkv", "webm"})
# HEIC/HEIF соцсети не принимают — конвертируем в JPEG в памяти.
HEIC_EXTENSIONS: frozenset[str] = frozenset({"heic", "heif"})
PUBLIC_PREFIX = "public://yandex/"

_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "heic": "image/heic",
    "heif": "image/heif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
}
# Известные фото-расширения (для is_image / выбора типа медиа).
IMAGE_EXTENSIONS: frozenset[str] = frozenset(_CONTENT_TYPES)


def extension(name: str) -> str:
    """Вернуть расширение файла в нижнем регистре (без точки) или пустую строку."""
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def is_video(name: str) -> bool:
    """Является ли файл видео (по расширению)."""
    return extension(name) in VIDEO_EXTENSIONS


def is_image(name: str) -> bool:
    """Является ли файл изображением (известное фото-расширение)."""
    return extension(name) in IMAGE_EXTENSIONS


def content_type(name: str) -> str:
    """MIME-тип по расширению файла (fallback — ``application/octet-stream``)."""
    return _CONTENT_TYPES.get(extension(name), "application/octet-stream")


def sanitize_filename(name: str) -> str:
    """Безопасное имя файла для multipart: без путей и управляющих символов."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in '"\r\n\t')
    return cleaned or "media"


@dataclass(slots=True)
class MediaAttachmentDescriptor:
    """Нормализованное описание одного медиа-вложения (из ``media_items``)."""

    media_asset_id: int | None
    file_name: str
    media_kind: str  # image | video
    media_path: str | None
    yandex_disk_path: str | None

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "MediaAttachmentDescriptor":
        file_name = str(item.get("file_name") or "")
        kind = str(item.get("media_kind") or ("video" if is_video(file_name) else "image"))
        raw_id = item.get("id")
        return cls(
            media_asset_id=raw_id if isinstance(raw_id, int) else None,
            file_name=file_name,
            media_kind=kind,
            media_path=item.get("media_path") if isinstance(item.get("media_path"), str) else None,
            yandex_disk_path=(
                item.get("yandex_disk_path")
                if isinstance(item.get("yandex_disk_path"), str)
                else None
            ),
        )


class SupportsPublicMediaDownload(Protocol):
    """Контракт загрузчика публичного медиа (структурный, для DI и тестов)."""

    def download_public_media(self, disk_path: str, file_name: str) -> Any:
        """Вернуть объект с полями ``bytes``, ``content_type``, ``file_name``."""
        ...


class SupportsImageConversion(Protocol):
    """Контракт конвертера изображений (HEIC/HEIF → JPEG в памяти + трансформации доставки)."""

    def enhance_image_bytes(
        self, image_bytes: bytes, profile: str, operations: dict[str, bool] | None = None
    ) -> Any:
        """Вернуть объект с полем ``output_bytes`` (сконвертированные байты)."""
        ...

    def transform_bytes(self, image_bytes: bytes, transform: str) -> tuple[bytes, int, int]:
        """Применить трансформацию доставки (ресайз/кроп) → (bytes, width, height)."""
        ...


def load_item_bytes(
    item: dict[str, Any], downloader: SupportsPublicMediaDownload | None
) -> tuple[bytes | None, str]:
    """Прочитать байты одного медиа группы (локальная копия или Яндекс Диск).

    Приоритет — локальный ``media_path`` (одобренная enhanced-копия); иначе
    публичная папка Яндекс Диска через ``downloader``. Если источник недоступен —
    ``(None, file_name)`` (публикацию не роняем, вызывающий добавит предупреждение).
    """
    media_path = item.get("media_path")
    if isinstance(media_path, str) and media_path:
        path = Path(media_path)
        if not path.is_file():
            return None, path.name
        return path.read_bytes(), path.name

    disk_path = item.get("yandex_disk_path")
    file_name = str(
        item.get("file_name")
        or (Path(disk_path).name if isinstance(disk_path, str) else "")
        or "photo.jpg"
    )
    if (
        isinstance(disk_path, str)
        and disk_path.startswith(PUBLIC_PREFIX)
        and downloader is not None
    ):
        downloaded = downloader.download_public_media(disk_path, file_name)
        data: bytes = downloaded.bytes
        return data, file_name
    return None, file_name


def maybe_convert_heic(
    content: bytes, file_name: str, processor: SupportsImageConversion | None
) -> tuple[bytes, str, str]:
    """HEIC/HEIF → JPEG в памяти (best-effort). Оригинал не перезаписывается.

    Если формат не HEIC/HEIF, процессор не задан или конвертация не удалась —
    возвращаем исходные байты (публикацию не роняем).
    """
    if extension(file_name) not in HEIC_EXTENSIONS or processor is None:
        return content, file_name, content_type(file_name)
    try:
        result = processor.enhance_image_bytes(content, "minimal")
        converted: bytes = result.output_bytes
    except Exception:  # noqa: BLE001 — любая ошибка конвертации → грузим оригинал
        return content, file_name, content_type(file_name)
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    return converted, f"{stem}.jpg", "image/jpeg"
