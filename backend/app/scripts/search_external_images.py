"""CLI поиска внешних изображений (fake-провайдер, без сети).

Запуск:
  make search-external-images project_slug=teeon query="шелкография"
  python -m app.scripts.search_external_images --project-slug teeon --query "шелкография" --limit 5
"""

import argparse

from app.api.deps import (
    get_external_image_provider_registry,
    get_external_image_search_service,
)
from app.db.session import get_sessionmaker
from app.repositories.post_repository import PostNotFoundError
from app.repositories.topic_repository import TopicNotFoundError
from app.schemas.external_image import ExternalImageSearchRequest
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов поиска внешних изображений."""
    parser = argparse.ArgumentParser(description="Поиск внешних изображений (fake)")
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--project-slug", default=None)
    parser.add_argument("--topic-id", type=int, default=None)
    parser.add_argument("--post-id", type=int, default=None)
    parser.add_argument("--query", default=None)
    parser.add_argument("--limit", type=int, default=10)
    return parser


def main() -> None:
    """Точка входа CLI поиска внешних изображений."""
    args = build_parser().parse_args()
    request = ExternalImageSearchRequest(
        project_id=args.project_id,
        project_slug=args.project_slug,
        topic_id=args.topic_id,
        post_id=args.post_id,
        query=args.query,
        limit=args.limit,
    )

    service = get_external_image_search_service(get_external_image_provider_registry())
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.search_images(db, request)
        except (ProjectNotFoundError, TopicNotFoundError, PostNotFoundError) as exc:
            print(f"Ошибка: {exc}")
            return

    print(
        f"Проект {result.project_slug}: запрос «{result.query}» | "
        f"найдено={result.found_count} создано={result.created} пропущено={result.skipped}"
    )
    for candidate in result.candidates:
        print(
            f"  id={candidate.id} [{candidate.review_status}] {candidate.title} "
            f"(commercial={candidate.commercial_use_allowed}, logo={candidate.contains_logo})"
        )
    for warning in result.warnings:
        print(f"  ! {warning}")


if __name__ == "__main__":
    main()
