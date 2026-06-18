"""Повторное тегирование медиа проекта (без сети и AI).

Запуск:
  make retag-media project_slug=teeon
  python -m app.scripts.retag_media --project-slug teeon
  python -m app.scripts.retag_media --project-id 1

Не требует YANDEX_DISK_TOKEN: данные берутся из БД, Диск не дёргается.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.media_analysis_service import MediaAnalysisService
from app.services.media_status_service import MediaStatusService
from app.services.media_tagging_service import MediaTaggingService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def main() -> None:
    """Точка входа CLI повторного тегирования."""
    parser = argparse.ArgumentParser(description="Повторное тегирование медиа проекта")
    parser.add_argument("--project-slug", default=None, help="slug проекта, например teeon")
    parser.add_argument("--project-id", type=int, default=None, help="id проекта")
    args = parser.parse_args()

    if not args.project_slug and args.project_id is None:
        print("Укажите --project-slug или --project-id.")
        return

    service = MediaAnalysisService(
        tagging_service=MediaTaggingService(),
        status_service=MediaStatusService(),
    )

    factory = get_sessionmaker()
    with factory() as db:
        try:
            if args.project_id is not None:
                result = service.retag_project_media(db, args.project_id)
            else:
                result = service.retag_project_media_by_slug(db, args.project_slug)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return

    print(f"Проект: {result['project_slug']} (id={result['project_id']})")
    print(f"Обработано: {result['processed']}")
    print(f"Обновлено:  {result['updated']}")
    print(f"Пропущено:  {result['skipped']}")
    if result["errors"]:
        print("Ошибки:")
        for error in result["errors"]:
            print(f"  ! {error}")
    else:
        print("Ошибки: нет")


if __name__ == "__main__":
    main()
