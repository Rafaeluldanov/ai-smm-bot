"""CLI: превью групп похожих медиа проекта (без создания постов и без сети).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.preview_media_groups \\
      --project-slug teeon \\
      --tag футболка \\
      --max-groups 10 \\
      --limit-media 5 \\
      --include-videos

Показывает: group_key, matched_tags, media_count/image_count/video_count, id
медиа, имена файлов, статус/источник/лицензию и предупреждения. Ничего не
сохраняет и не публикует.
"""

import argparse

from sqlalchemy.orm import Session

from app.api.deps import get_media_grouping_service
from app.db.session import get_sessionmaker
from app.repositories import media_asset_repository
from app.services.media_grouping_service import MediaGroupCandidate, MediaGroupingService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов превью групп медиа."""
    parser = argparse.ArgumentParser(description="Превью групп похожих медиа проекта")
    parser.add_argument("--project-slug", default="teeon")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--max-groups", type=int, default=10)
    parser.add_argument("--limit-media", type=int, default=5)
    parser.add_argument(
        "--include-videos",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="учитывать видео (по умолчанию да; --no-include-videos — только фото)",
    )
    return parser


def collect_groups(
    db: Session, service: MediaGroupingService, args: argparse.Namespace
) -> list[MediaGroupCandidate]:
    """Собрать группы медиа по аргументам (без побочных эффектов)."""
    return service.group_project_media(
        db,
        args.project_slug,
        tag=args.tag,
        max_groups=args.max_groups,
        limit_media=args.limit_media,
        include_videos=args.include_videos,
    )


def print_groups(db: Session, groups: list[MediaGroupCandidate]) -> None:
    """Напечатать группы с деталями каждого медиа."""
    if not groups:
        print("Групп медиа не найдено (нет подходящих собственных approved-медиа).")
        return
    print(f"Найдено групп: {len(groups)}")
    for index, group in enumerate(groups, start=1):
        print(
            f"\n=== Группа {index}: {group.group_key} [{group.group_type}] score={group.score} ==="
        )
        print(f"  matched_tags: {', '.join(group.matched_tags) or '—'}")
        print(
            f"  media_count={group.media_count} "
            f"(фото={group.image_count}, видео={group.video_count})"
        )
        print(f"  media ids: {group.media_asset_ids}")
        for media_id in group.media_asset_ids:
            asset = media_asset_repository.get_media_asset_by_id(db, media_id)
            if asset is None:
                print(f"    - id={media_id}: <не найден>")
                continue
            print(
                f"    - id={asset.id} | {asset.file_name} | "
                f"status={asset.status} source={asset.source_type} "
                f"license={asset.license_type}"
            )
        for warning in group.warnings:
            print(f"  ! {warning}")


def main() -> None:
    """Точка входа CLI превью групп медиа."""
    args = build_parser().parse_args()
    service = get_media_grouping_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            groups = collect_groups(db, service, args)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return
        print_groups(db, groups)


if __name__ == "__main__":
    main()
