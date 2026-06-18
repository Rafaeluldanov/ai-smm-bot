"""Сводка по тегам медиа проекта (без сети и AI).

Запуск:
  make media-summary project_slug=teeon
  python -m app.scripts.media_summary --project-slug teeon
"""

import argparse

from app.db.session import get_sessionmaker
from app.repositories import project_repository
from app.services.media_analysis_service import MediaAnalysisService
from app.services.media_status_service import MediaStatusService
from app.services.media_tagging_service import MediaTaggingService

_GROUPS = [
    "products",
    "technologies",
    "details",
    "materials",
    "colors",
    "categories",
    "use_cases",
    "audiences",
]


def main() -> None:
    """Точка входа CLI сводки по тегам."""
    parser = argparse.ArgumentParser(description="Сводка по тегам медиа проекта")
    parser.add_argument("--project-slug", default=None, help="slug проекта, например teeon")
    args = parser.parse_args()

    service = MediaAnalysisService(
        tagging_service=MediaTaggingService(),
        status_service=MediaStatusService(),
    )

    factory = get_sessionmaker()
    with factory() as db:
        project_id = None
        if args.project_slug:
            project = project_repository.get_project_by_slug(db, args.project_slug)
            if project is None:
                print(f"Проект не найден: {args.project_slug}")
                return
            project_id = project.id
        summary = service.get_tags_summary(db, project_id=project_id)

    print(f"Всего медиа: {summary['total_assets']}")
    for group in _GROUPS:
        counts = summary.get(group, {})
        if not counts:
            continue
        print(f"\n{group}:")
        for tag, count in counts.items():
            print(f"  {tag}: {count}")


if __name__ == "__main__":
    main()
