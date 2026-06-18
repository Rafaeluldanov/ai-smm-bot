"""Ручная синхронизация медиа проекта с Яндекс Диском.

Запуск: ``make sync-media project_slug=teeon``
или: ``python -m app.scripts.sync_media --project-slug teeon``

Требует заданного ``YANDEX_DISK_TOKEN`` в окружении/.env. Не используется в make check.
"""

import argparse

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.integrations.yandex_disk.client import YandexDiskClient, YandexDiskError
from app.services.media_tagging_service import MediaTaggingService
from app.services.project_media_paths import UnknownProjectError
from app.services.yandex_disk_media_sync_service import (
    ProjectNotFoundError,
    YandexDiskMediaSyncService,
)


def main() -> None:
    """Точка входа CLI-скрипта синхронизации."""
    parser = argparse.ArgumentParser(description="Синхронизация медиа проекта с Яндекс Диска")
    parser.add_argument("--project-slug", required=True, help="slug проекта, например teeon")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.yandex_disk_token:
        print("YANDEX_DISK_TOKEN не задан — синхронизация невозможна. Заполните .env.")
        return

    client = YandexDiskClient(
        token=settings.yandex_disk_token,
        base_url=settings.yandex_disk_base_url,
    )
    service = YandexDiskMediaSyncService(client=client, tagging_service=MediaTaggingService())

    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.sync_project_media_by_slug(db, args.project_slug)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return
        except UnknownProjectError as exc:
            print(f"Ошибка: {exc}")
            return
        except YandexDiskError as exc:
            print(f"Ошибка Яндекс Диска: {exc}")
            return

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


if __name__ == "__main__":
    main()
