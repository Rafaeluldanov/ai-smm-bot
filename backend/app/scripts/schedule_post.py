"""CLI планирования публикаций поста (без сети и AI).

Запуск:
  make schedule-post post_id=1
  python -m app.scripts.schedule_post --post-id 1 --platform telegram --platform vk \
      --scheduled-at 2026-06-18T12:00:00
"""

import argparse
from datetime import datetime

from app.api.deps import get_post_publication_service, get_publication_platform_registry
from app.db.session import get_sessionmaker
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post_publication import PostScheduleRequest
from app.services.post_publication_service import PostNotPublishableError


def parse_datetime(value: str | None) -> datetime | None:
    """Разобрать ISO-дату (или None). Вынесено для тестируемости."""
    if not value:
        return None
    return datetime.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов планирования."""
    parser = argparse.ArgumentParser(description="Планирование публикаций поста")
    parser.add_argument("--post-id", type=int, required=True)
    parser.add_argument("--platform", action="append", default=None)
    parser.add_argument("--scheduled-at", default=None)
    return parser


def main() -> None:
    """Точка входа CLI планирования."""
    args = build_parser().parse_args()
    platforms = args.platform or ["telegram", "vk"]
    request = PostScheduleRequest(
        platforms=platforms, scheduled_at=parse_datetime(args.scheduled_at)
    )

    service = get_post_publication_service(get_publication_platform_registry())
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.schedule_post(db, args.post_id, request)
        except (PostNotFoundError, PostNotPublishableError) as exc:
            print(f"Ошибка: {exc}")
            return

    print(f"Пост {result.post_id}: статус {result.post_status}")
    for publication in result.publications:
        print(
            f"  [{publication.platform}] {publication.status} "
            f"target={publication.target_id} scheduled_at={publication.scheduled_at}"
        )
    for warning in result.warnings:
        print(f"  ! {warning}")


if __name__ == "__main__":
    main()
