"""CLI публикации всех созревших публикаций (без реальной сети).

Запуск:
  make publish-due
  python -m app.scripts.publish_due --now 2026-06-18T12:00:00
"""

import argparse

from app.api.deps import get_post_publication_service, get_publication_platform_registry
from app.db.session import get_sessionmaker
from app.scripts.schedule_post import parse_datetime


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов публикации due-постов."""
    parser = argparse.ArgumentParser(description="Публикация созревших публикаций")
    parser.add_argument("--now", default=None)
    return parser


def main() -> None:
    """Точка входа CLI публикации due-постов."""
    args = build_parser().parse_args()
    now = parse_datetime(args.now)

    service = get_post_publication_service(get_publication_platform_registry())
    factory = get_sessionmaker()
    with factory() as db:
        result = service.publish_due_publications(db, now)

    print(
        f"Обработано постов={result.processed_posts}, публикаций={result.processed_publications} | "
        f"опубликовано={result.published_count} ошибок={result.failed_count} "
        f"пропущено={result.skipped_count}"
    )
    for warning in result.warnings:
        print(f"  ! {warning}")


if __name__ == "__main__":
    main()
