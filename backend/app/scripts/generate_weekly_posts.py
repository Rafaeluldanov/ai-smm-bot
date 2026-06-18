"""Пакетная генерация постов на неделю(и) (без сети и AI).

Запуск:
  make generate-weekly-posts project_slug=teeon
  python -m app.scripts.generate_weekly_posts --project-slug teeon \
      --weeks 1 --posts-per-week 3 --business-priority футболки=100
"""

import argparse

from app.api.deps import get_post_generation_service
from app.db.session import get_sessionmaker
from app.schemas.post import WeeklyPostGenerationRequest
from app.scripts.select_topics import parse_business_priorities
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def main() -> None:
    """Точка входа CLI пакетной генерации постов."""
    parser = argparse.ArgumentParser(description="Генерация постов на неделю(и) для проекта")
    parser.add_argument("--project-slug", default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--weeks", type=int, default=1)
    parser.add_argument("--posts-per-week", type=int, default=3)
    parser.add_argument("--business-priority", action="append", default=None)
    args = parser.parse_args()

    if not args.project_slug and args.project_id is None:
        print("Укажите --project-slug или --project-id.")
        return

    request = WeeklyPostGenerationRequest(
        project_id=args.project_id,
        project_slug=args.project_slug,
        weeks=args.weeks,
        posts_per_week=args.posts_per_week,
        business_priorities=parse_business_priorities(args.business_priority) or None,
    )

    service = get_post_generation_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.generate_weekly_posts(db, request)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return

    print(f"Проект: {result.project_slug} (id={result.project_id})")
    print(f"Сгенерировано постов: {result.generated_count}\n")
    for post in result.posts:
        print(f"[{post.status}] id={post.id} | {post.title}")
        print(f"        медиа: {post.media_asset_id} | хэштеги: {' '.join(post.hashtags)}")
    if result.warnings:
        print("\nПредупреждения:")
        for warning in result.warnings:
            print(f"  ! {warning}")


if __name__ == "__main__":
    main()
