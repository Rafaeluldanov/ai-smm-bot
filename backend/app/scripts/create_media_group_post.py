"""CLI: создать пост по группе похожих медиа (needs_review; без сети/публикации).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.create_media_group_post \\
      --project-slug teeon \\
      --tag футболка \\
      --limit-media 5 \\
      --status needs_review

Берёт лучшую группу медиa проекта (при указанном ``--tag`` — по этому тегу),
собирает пост с SEO-ссылкой на сайт и группой медиа и сохраняет его. Ничего не
публикует: дальше — ручное согласование, планирование и dry-run превью.
"""

import argparse

from sqlalchemy.orm import Session

from app.api.deps import get_media_grouping_service
from app.db.session import get_sessionmaker
from app.models.post import Post
from app.services.media_grouping_service import MediaGroupingService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания поста из группы медиа."""
    parser = argparse.ArgumentParser(description="Создать пост по группе похожих медиа")
    parser.add_argument("--project-slug", default="teeon")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--limit-media", type=int, default=5)
    parser.add_argument("--status", default="needs_review")
    parser.add_argument(
        "--include-videos",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="учитывать видео в группе (в VK они пропускаются с предупреждением)",
    )
    return parser


def create_from_args(
    db: Session, service: MediaGroupingService, args: argparse.Namespace
) -> Post | None:
    """Создать пост по лучшей группе медиа. Вернуть Post или None, если групп нет."""
    groups = service.group_project_media(
        db,
        args.project_slug,
        tag=args.tag,
        max_groups=1,
        limit_media=args.limit_media,
        include_videos=args.include_videos,
    )
    if not groups:
        return None
    return service.create_post_from_media_group(
        db, args.project_slug, groups[0], status=args.status
    )


def _print_post(post: Post) -> None:
    notes = post.generation_notes or {}
    warnings = notes.get("warnings") or []
    text_preview = (post.vk_text or "")[:200]
    print(f"Создан пост id={post.id}")
    print(f"  status: {post.status}")
    print(f"  title: {post.title}")
    print(f"  media_asset_id (главное): {post.media_asset_id}")
    print(f"  media_asset_ids: {notes.get('media_asset_ids')}")
    print(
        f"  media_count: {notes.get('media_count')} "
        f"(фото={notes.get('image_count')}, видео={notes.get('video_count')})"
    )
    print(f"  selected_for_vk_upload: {notes.get('selected_for_vk_upload')}")
    print(f"  text (превью): {text_preview!r}")
    for warning in warnings:
        print(f"  ! {warning}")
    print("\nСледующие шаги (ручные, ничего не публикуется автоматически):")
    print(f"  python -m app.scripts.review_post --post-id {post.id} --action submit")
    print(f"  python -m app.scripts.schedule_post --post-id {post.id}")
    print(f"  python -m app.scripts.publish_post --post-id {post.id} --dry-run")


def main() -> None:
    """Точка входа CLI создания поста по группе медиа."""
    args = build_parser().parse_args()
    service = get_media_grouping_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            post = create_from_args(db, service, args)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return
        if post is None:
            print(
                f"Подходящих групп медиа для проекта '{args.project_slug}'"
                + (f" по тегу '{args.tag}'" if args.tag else "")
                + " не найдено — пост не создан."
            )
            return
        _print_post(post)


if __name__ == "__main__":
    main()
