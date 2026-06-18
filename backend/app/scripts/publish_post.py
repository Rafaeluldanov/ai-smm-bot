"""CLI публикации поста (без реальной сети — клиенты безопасны/мокабельны).

Запуск:
  make publish-post post_id=1
  python -m app.scripts.publish_post --post-id 1 --platform telegram --force
"""

import argparse

from app.api.deps import get_post_publication_service, get_publication_platform_registry
from app.db.session import get_sessionmaker
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post_publication import PostPublishRequest
from app.services.post_publication_service import PostNotPublishableError


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов публикации."""
    parser = argparse.ArgumentParser(description="Публикация поста в Telegram/VK")
    parser.add_argument("--post-id", type=int, required=True)
    parser.add_argument("--platform", action="append", default=None)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    """Точка входа CLI публикации."""
    args = build_parser().parse_args()
    request = PostPublishRequest(platforms=args.platform, force=args.force)

    service = get_post_publication_service(get_publication_platform_registry())
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.publish_post(db, args.post_id, request)
        except (PostNotFoundError, PostNotPublishableError) as exc:
            print(f"Ошибка: {exc}")
            return

    print(
        f"Пост {result.post_id}: статус {result.post_status} | "
        f"опубликовано={result.published_count} ошибок={result.failed_count} "
        f"пропущено={result.skipped_count}"
    )
    for publication in result.publications:
        print(
            f"  [{publication.platform}] {publication.status} "
            f"external_id={publication.external_post_id} error={publication.error_message}"
        )
    for warning in result.warnings:
        print(f"  ! {warning}")


if __name__ == "__main__":
    main()
