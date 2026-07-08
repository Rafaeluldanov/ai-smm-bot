"""CLI публикации поста (без реальной сети — клиенты безопасны/мокабельны).

Запуск:
  make publish-post post_id=1
  python -m app.scripts.publish_post --post-id 1 --platform telegram --force
  python -m app.scripts.publish_post --post-id 1 --dry-run   # превью без отправки
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
    parser.add_argument(
        "--dry-run", action="store_true", help="показать payload публикации без отправки"
    )
    return parser


def _print_preview(post_id: int, request: PostPublishRequest) -> None:
    service = get_post_publication_service(get_publication_platform_registry())
    factory = get_sessionmaker()
    with factory() as db:
        try:
            preview = service.preview_publication(db, post_id, request)
        except PostNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"DRY-RUN: пост {preview.post_id} | статус {preview.post_status} (ничего не отправлено)")
    for item in preview.items:
        print(
            f"  [{item.platform}] target={item.target_id} "
            f"live_enabled={item.live_enabled} would_send={item.would_send}"
        )
        print(
            f"    media_kind={item.media_kind} media_count={item.media_count} "
            f"would_attach_media={item.would_attach_media}"
        )
        print(f"    media_asset_ids={item.media_asset_ids} media_source={item.media_source}")
        print(f"    preferred_media_path={item.preferred_media_path}")
        caps = item.platform_capabilities
        if caps is not None:
            print(
                f"    capabilities: text={caps.supports_text} image={caps.supports_image} "
                f"image_group={caps.supports_image_group} video={caps.supports_video} "
                f"max_images={caps.max_images} live_implemented={caps.live_implemented}"
            )
        if item.unsupported_media_reason:
            print(f"    unsupported_media_reason: {item.unsupported_media_reason}")
        for warning in item.media_warnings:
            print(f"    ! {warning}")
        print(f"    text={item.text[:120]!r}")


def main() -> None:
    """Точка входа CLI публикации."""
    args = build_parser().parse_args()
    request = PostPublishRequest(platforms=args.platform, force=args.force)

    if args.dry_run:
        _print_preview(args.post_id, request)
        return

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
