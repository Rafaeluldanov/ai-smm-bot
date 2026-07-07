"""CLI автономного прогона (без сети, AI и реальных публикаций).

Запуск:
  make autonomous-run project_slug=teeon
  make autonomous-dry-run project_slug=teeon
  python -m app.scripts.autonomous_run --project-slug teeon --mode semi_auto \
      --business-priority футболки=100 --business-priority худи=80
"""

import argparse

from app.api.deps import get_autonomous_pipeline_service
from app.db.session import get_sessionmaker
from app.schemas.autonomous import AutonomousModeSettings, AutonomousRunRequest
from app.scripts.select_topics import parse_business_priorities
from app.services.autonomous_pipeline_service import AutonomousValidationError
from app.services.seo_content_sources import UnknownSeoProjectError, get_default_publication_vector
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов автономного прогона."""
    parser = argparse.ArgumentParser(description="Автономный прогон pipeline по проекту")
    parser.add_argument("--project-slug", default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument(
        "--mode",
        default="semi_auto",
        choices=["dry_run", "semi_auto", "auto_generate", "auto_schedule", "auto_publish"],
    )
    parser.add_argument("--weeks", type=int, default=1)
    parser.add_argument("--posts-per-week", type=int, default=3)
    parser.add_argument("--business-priority", action="append", default=None)
    parser.add_argument(
        "--use-default-publication-vector",
        action="store_true",
        help="Взять бизнес-приоритеты из SEO-профиля проекта, если не заданы вручную",
    )
    parser.add_argument("--allow-external-images", action="store_true")
    parser.add_argument("--allow-auto-schedule", action="store_true")
    parser.add_argument("--allow-auto-publish", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def resolve_business_priorities(args: argparse.Namespace) -> dict[str, int] | None:
    """Приоритеты из CLI сильнее пресета SEO-профиля.

    Если пользователь передал ``--business-priority`` — используем их. Иначе, при
    ``--use-default-publication-vector`` и известном проекте, берём дефолтный
    вектор публикаций из SEO-профиля.
    """
    manual = parse_business_priorities(args.business_priority) or None
    if manual is not None:
        return manual
    if getattr(args, "use_default_publication_vector", False) and args.project_slug:
        try:
            return get_default_publication_vector(args.project_slug) or None
        except UnknownSeoProjectError:
            return None
    return None


def build_request(args: argparse.Namespace) -> AutonomousRunRequest:
    """Собрать запрос прогона из аргументов CLI."""
    settings = AutonomousModeSettings(
        allow_external_images=args.allow_external_images,
        allow_auto_schedule=args.allow_auto_schedule,
        allow_auto_publish=args.allow_auto_publish,
        dry_run=args.dry_run,
    )
    mode = "dry_run" if args.dry_run else args.mode
    return AutonomousRunRequest(
        project_id=args.project_id,
        project_slug=args.project_slug,
        mode=mode,
        weeks=args.weeks,
        posts_per_week=args.posts_per_week,
        business_priorities=resolve_business_priorities(args),
        settings=settings,
    )


def main() -> None:
    """Точка входа CLI автономного прогона."""
    args = build_parser().parse_args()
    if not args.project_slug and args.project_id is None:
        print("Укажите --project-slug или --project-id.")
        return

    request = build_request(args)
    service = get_autonomous_pipeline_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.run_pipeline(db, request)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return
        except AutonomousValidationError as exc:
            print(f"Некорректный запрос: {exc}")
            return

    run = result.run
    print(f"Прогон id={run.id} | режим={run.mode} | статус={run.status}")
    print(
        f"Темы={result.selected_topics} посты={result.generated_posts} "
        f"needs_media={result.posts_needing_media} внешние={result.external_candidates} "
        f"на ревью={result.submitted_for_review} запланировано={result.scheduled_publications} "
        f"опубликовано={result.published_publications}"
    )
    for warning in result.warnings:
        print(f"  ! {warning}")
    print(f"Шагов: {len(result.steps)}")


if __name__ == "__main__":
    main()
