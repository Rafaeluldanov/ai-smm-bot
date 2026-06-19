"""Сводка по производным вариантам улучшения медиа.

Запуск:
  make media-enhancement-summary project_slug=teeon
  python -m app.scripts.media_enhancement_summary --project-slug teeon

Показывает количество вариантов по статусам и типам. Не входит в make check.
"""

import argparse

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.repositories import project_repository
from app.scripts.enhance_media import build_enhancement_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов сводки улучшений."""
    parser = argparse.ArgumentParser(description="Сводка по улучшениям медиа проекта")
    parser.add_argument("--project-slug", default=None, help="slug проекта (или все проекты)")
    return parser


def main() -> None:
    """Точка входа CLI сводки улучшений."""
    args = build_parser().parse_args()
    settings = get_settings()
    service = build_enhancement_service(settings)

    factory = get_sessionmaker()
    with factory() as db:
        project_id = None
        if args.project_slug:
            project = project_repository.get_project_by_slug(db, args.project_slug)
            if project is None:
                print(f"Проект не найден: {args.project_slug}")
                return
            project_id = project.id
        summary = service.get_enhancement_summary(db, project_id=project_id)

    print(f"Всего вариантов: {summary.total_variants}")
    print("По статусам:")
    for name, count in summary.by_status.items():
        print(f"  {name}: {count}")
    print("По типам:")
    for name, count in summary.by_variant_type.items():
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
