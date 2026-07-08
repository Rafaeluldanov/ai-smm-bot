"""CLI: превью, что уйдёт на каждую платформу для групп медиа проекта.

Ничего НЕ создаёт и НЕ отправляет. Берёт группы медиа по тегу и показывает по
каждой платформе (VK/Telegram/Instagram/YouTube/RuTube и будущим):
- какие media-ассеты найдены;
- поддерживает ли платформа эти медиа (capability-слой);
- что именно ушло бы (image_group/image/video/none) и предупреждения.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.preview_media_platforms \\
      --project-slug teeon --tag футболка \\
      --platforms "telegram,vk,instagram,youtube,rutube"
"""

import argparse

from sqlalchemy.orm import Session

from app.api.deps import get_media_grouping_service
from app.db.session import get_sessionmaker
from app.integrations import platform_capabilities
from app.services.media_grouping_service import MediaGroupCandidate, MediaGroupingService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

_DEFAULT_PLATFORMS = "telegram,vk,instagram,youtube,rutube"


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов мультиплатформенного превью."""
    parser = argparse.ArgumentParser(description="Превью медиа по платформам (без публикации)")
    parser.add_argument("--project-slug", default="teeon")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--platforms", default=_DEFAULT_PLATFORMS)
    parser.add_argument("--limit-media", type=int, default=10)
    parser.add_argument("--max-groups", type=int, default=3)
    parser.add_argument("--include-videos", action=argparse.BooleanOptionalAction, default=True)
    return parser


def parse_platforms(raw: str) -> list[str]:
    """Разобрать список платформ из строки через запятую."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def collect_groups(
    db: Session, service: MediaGroupingService, args: argparse.Namespace
) -> list[MediaGroupCandidate]:
    """Собрать группы медиа проекта (без побочных эффектов)."""
    return service.group_project_media(
        db,
        args.project_slug,
        tag=args.tag,
        max_groups=args.max_groups,
        limit_media=args.limit_media,
        include_videos=args.include_videos,
    )


def print_platform_preview(
    db: Session,
    service: MediaGroupingService,
    project_slug: str,
    groups: list[MediaGroupCandidate],
    platforms: list[str],
) -> None:
    """Напечатать по каждой группе, что уйдёт на каждую платформу."""
    if not groups:
        print("Групп медиа не найдено (нет подходящих собственных approved-медиа).")
        return
    for index, group in enumerate(groups, start=1):
        draft = service.build_post_draft_from_group(db, project_slug, group)
        media_files = draft.generation_notes.get("media_files") or []
        assert isinstance(media_files, list)
        print(f"\n=== Группа {index}: {group.group_key} [{group.group_type}] ===")
        print(
            f"  media_count={group.media_count} "
            f"(фото={group.image_count}, видео={group.video_count}) ids={group.media_asset_ids}"
        )
        for platform in platforms:
            caps = platform_capabilities.get_capabilities(platform)
            if caps is None:
                print(f"  [{platform}] неизвестная платформа")
                continue
            route = platform_capabilities.route_media(caps, media_files)
            live = (
                "live-ready"
                if platform not in platform_capabilities.LIVE_NOT_IMPLEMENTED
                else "dry-run only"
            )
            print(
                f"  [{platform}] would_attach_media={route.would_attach_media} "
                f"selected={route.selected_media_kind} x{route.selected_count} ({live})"
            )
            if route.unsupported_media_reason:
                print(f"      unsupported: {route.unsupported_media_reason}")
            for warning in route.media_warnings:
                print(f"      ! {warning}")


def main() -> None:
    """Точка входа CLI мультиплатформенного превью."""
    args = build_parser().parse_args()
    platforms = parse_platforms(args.platforms)
    service = get_media_grouping_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            groups = collect_groups(db, service, args)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return
        print_platform_preview(db, service, args.project_slug, groups, platforms)


if __name__ == "__main__":
    main()
