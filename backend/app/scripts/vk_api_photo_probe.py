"""CLI: проверить, какая VK API стратегия загрузки фото работает с текущим токеном.

Диагностика БЕЗ публикации на стену (``wall.post`` не вызывается) и БЕЗ OAuth/браузера.
- без ``--allow-upload`` — только безопасные read-проверки (groups.getById,
  photos.getWallUploadServer, photos.getAlbums), файл не грузится;
- с ``--allow-upload true`` — реальная загрузка тестового 1x1 JPEG на wall-upload и в
  альбом группы (но БЕЗ ``wall.post``).

Токен VK НИКОГДА не печатается. Community-token обычно даёт error 27 на wall —
тогда рекомендуется album-стратегия.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.vk_api_photo_probe --strategy auto
"""

import argparse
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.integrations.vk.client import _TINY_JPEG, VKPublishingClient

PROBE_DIR = Path("tmp/vk_probe")


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов probe."""
    parser = argparse.ArgumentParser(description="VK API photo upload probe (без wall.post)")
    parser.add_argument("--strategy", default="auto", choices=["auto", "wall", "album"])
    parser.add_argument("--allow-upload", default="false")
    parser.add_argument("--album-id", default=None)
    parser.add_argument("--album-title", default=None)
    parser.add_argument("--group-id", default=None)
    parser.add_argument("--image-path", default=None)
    return parser


def prepare_probe_image(image_path: str | None) -> bytes:
    """Вернуть байты тестовой картинки (из --image-path или дефолтный 1x1 JPEG)."""
    if image_path:
        path = Path(image_path)
        if path.is_file():
            return path.read_bytes()
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    default = PROBE_DIR / "probe.jpg"
    default.write_bytes(_TINY_JPEG)
    return _TINY_JPEG


def _fmt(section: dict[str, Any]) -> str:
    if section.get("ok"):
        extra = ""
        if section.get("attachment"):
            extra = f" attachment={section['attachment']}"
        elif section.get("album_id") is not None:
            extra = f" album_id={section['album_id']}"
        return f"ok{extra}"
    code = section.get("error_code")
    msg = section.get("error_msg")
    return f"error code={code} msg={msg}"


def print_result(result: dict[str, Any]) -> None:
    """Напечатать безопасный итог probe (без токена)."""
    if result.get("error"):
        print(f"PROBE ERROR: {result['error']}")
        return
    print(f"GROUP: {_fmt(result.get('group', {}))} (group_id={result.get('group_id')})")
    print(f"WALL:  {_fmt(result.get('wall', {}))}")
    print(f"ALBUM: {_fmt(result.get('album', {}))}")
    print(f"RECOMMENDED_STRATEGY={result.get('recommended_strategy', 'none')}")
    if not result.get("allow_upload"):
        print("(read-only probe — файл не загружался; для upload-проверки: --allow-upload true)")


def run(
    client: VKPublishingClient,
    *,
    allow_upload: bool,
    group_id: str | None,
    album_id: str | None,
    album_title: str | None,
    image_bytes: bytes | None,
) -> dict[str, Any]:
    """Ядро: probe стратегий загрузки фото. Вернуть структурированный результат."""
    result = client.probe_photo_strategies(
        group_id=group_id,
        allow_upload=allow_upload,
        image_bytes=image_bytes,
        album_id=album_id,
        album_title=album_title,
    )
    print_result(result)
    return result


def main() -> None:
    """Точка входа CLI probe (реальные VK API-вызовы; wall.post не выполняется)."""
    args = build_parser().parse_args()
    settings = get_settings()
    if not settings.vk_access_token:
        print("VK_ACCESS_TOKEN не задан — probe невозможен.")
        return

    allow_upload = _parse_bool(args.allow_upload)
    image_bytes = prepare_probe_image(args.image_path) if allow_upload else None

    client = VKPublishingClient(
        token=settings.vk_access_token,
        default_target_id=settings.vk_default_group_id,
        photo_upload_strategy=args.strategy,
        photo_album_id=args.album_id or settings.vk_photo_album_id,
        photo_album_title=args.album_title or settings.vk_photo_album_title,
    )
    run(
        client,
        allow_upload=allow_upload,
        group_id=args.group_id,
        album_id=args.album_id,
        album_title=args.album_title,
        image_bytes=image_bytes,
    )


if __name__ == "__main__":
    main()
