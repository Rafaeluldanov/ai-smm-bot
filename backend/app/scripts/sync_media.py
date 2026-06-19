"""Ручная синхронизация медиа проекта с Яндекс Диском.

Запуск:
  make sync-media project_slug=teeon          # приватный режим (OAuth-токен)
  make sync-public-media project_slug=teeon    # публичная ссылка SMM
  python -m app.scripts.sync_media --project-slug teeon
  python -m app.scripts.sync_media --project-slug teeon --public

Приватный режим требует ``YANDEX_DISK_TOKEN``. Публичный (``--public`` или
``YANDEX_DISK_PUBLIC_MODE=true``) читает публичную папку без токена. Не входит в
make check.
"""

import argparse

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.integrations.yandex_disk.client import (
    YandexDiskClient,
    YandexDiskError,
    YandexDiskPublicClient,
)
from app.schemas.media_asset import MediaAssetSyncResult
from app.services.media_tagging_service import MediaTaggingService
from app.services.project_media_paths import UnknownProjectError
from app.services.public_yandex_disk_media_sync_service import (
    PublicLinkNotConfiguredError,
    PublicYandexDiskMediaSyncService,
)
from app.services.yandex_disk_media_sync_service import (
    ProjectNotFoundError,
    YandexDiskMediaSyncService,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов синхронизации."""
    parser = argparse.ArgumentParser(description="Синхронизация медиа проекта с Яндекс Диска")
    parser.add_argument("--project-slug", required=True, help="slug проекта, например teeon")
    parser.add_argument(
        "--public", action="store_true", help="использовать публичную ссылку (без токена)"
    )
    return parser


def _sync_public(slug: str) -> MediaAssetSyncResult | None:
    settings = get_settings()
    if not settings.yandex_disk_public_smm_url:
        print("YANDEX_DISK_PUBLIC_SMM_URL не задан — публичная синхронизация невозможна.")
        return None
    service = PublicYandexDiskMediaSyncService(
        client=YandexDiskPublicClient(base_url=settings.yandex_disk_base_url),
        tagging_service=MediaTaggingService(),
        public_key=settings.yandex_disk_public_smm_url,
        root_folder=settings.yandex_disk_public_root_folder,
    )
    factory = get_sessionmaker()
    with factory() as db:
        try:
            return service.sync_project_media_by_slug_from_public_link(db, slug)
        except (ProjectNotFoundError, PublicLinkNotConfiguredError) as exc:
            print(f"Ошибка: {exc}")
        except YandexDiskError as exc:
            print(f"Ошибка Яндекс Диска: {exc}")
    return None


def _sync_private(slug: str) -> MediaAssetSyncResult | None:
    settings = get_settings()
    if not settings.yandex_disk_token:
        print("YANDEX_DISK_TOKEN не задан — синхронизация невозможна. Заполните .env.")
        return None
    service = YandexDiskMediaSyncService(
        client=YandexDiskClient(
            token=settings.yandex_disk_token, base_url=settings.yandex_disk_base_url
        ),
        tagging_service=MediaTaggingService(),
    )
    factory = get_sessionmaker()
    with factory() as db:
        try:
            return service.sync_project_media_by_slug(db, slug)
        except (ProjectNotFoundError, UnknownProjectError) as exc:
            print(f"Ошибка: {exc}")
        except YandexDiskError as exc:
            print(f"Ошибка Яндекс Диска: {exc}")
    return None


def _print_result(result: MediaAssetSyncResult) -> None:
    print(f"Проект: {result.project_slug} (id={result.project_id})")
    print("Просканированные папки:")
    for folder in result.scanned_folders:
        print(f"  - {folder}")
    print(f"Найдено файлов: {result.found_files}")
    print(f"Создано:        {result.created}")
    print(f"Обновлено:      {result.updated}")
    print(f"Пропущено:      {result.skipped}")
    if result.errors:
        print("Ошибки:")
        for error in result.errors:
            print(f"  ! {error}")
    else:
        print("Ошибки: нет")


def main() -> None:
    """Точка входа CLI-скрипта синхронизации."""
    args = build_parser().parse_args()
    use_public = args.public or get_settings().yandex_disk_public_mode

    mode = "публичный" if use_public else "приватный"
    print(f"Режим синхронизации: {mode}")

    result = _sync_public(args.project_slug) if use_public else _sync_private(args.project_slug)
    if result is not None:
        _print_result(result)


if __name__ == "__main__":
    main()
