"""Пакетно улучшить медиа проекта (создать производные копии).

Запуск:
  make enhance-project-media project_slug=teeon
  python -m app.scripts.enhance_project_media --project-slug teeon --status approved

Создаёт улучшенные КОПИИ (MediaAssetVariant); оригиналы не меняются. По
умолчанию берёт медиа со статусом ``approved`` (``--status all`` — все). Видео
пропускаются. Не входит в make check.
"""

import argparse

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.schemas.media_enhancement import (
    ProjectMediaEnhancementRequest,
    ProjectMediaEnhancementResult,
)
from app.scripts.enhance_media import build_enhancement_service
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов пакетного улучшения."""
    parser = argparse.ArgumentParser(description="Пакетно улучшить медиа проекта")
    parser.add_argument("--project-slug", required=True, help="slug проекта, например teeon")
    parser.add_argument("--profile", default=None, help="social_safe | product_clean | minimal")
    parser.add_argument(
        "--status", default="approved", help="фильтр статуса медиа (или 'all' — все)"
    )
    parser.add_argument("--limit", type=int, default=100, help="максимум медиа за прогон")
    parser.add_argument("--force", action="store_true", help="пересоздавать уже улучшенные")
    return parser


def _print_result(result: ProjectMediaEnhancementResult) -> None:
    print(f"Проект:    {result.project_slug} (id={result.project_id})")
    print(f"Профиль:   {result.profile}")
    print(f"Кандидаты: {result.total_candidates}")
    print(f"Улучшено:  {result.enhanced}")
    print(f"На review: {result.needs_review}")
    print(f"Пропущено: {result.skipped}")
    print(f"Ошибки:    {result.failed}")
    for error in result.errors:
        print(f"  ! {error}")


def main() -> None:
    """Точка входа CLI пакетного улучшения."""
    args = build_parser().parse_args()
    settings = get_settings()
    profile = args.profile or settings.media_enhancement_default_profile
    status = None if args.status == "all" else args.status
    request = ProjectMediaEnhancementRequest(
        project_slug=args.project_slug,
        status=status,
        limit=args.limit,
        profile=profile,
        force=args.force,
    )

    service = build_enhancement_service(settings)
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.enhance_project_media(db, request)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return
        _print_result(result)


if __name__ == "__main__":
    main()
