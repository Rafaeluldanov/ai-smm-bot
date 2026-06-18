"""Недельный контент-план для проекта (без сети и AI).

Запуск:
  make content-plan project_slug=teeon
  python -m app.scripts.content_plan --project-slug teeon --posts-per-week 3 --weeks 1
"""

import argparse

from app.db.session import get_sessionmaker
from app.schemas.topic import TopicSelectionRequest
from app.scripts.select_topics import parse_business_priorities
from app.services.market_signal_provider import StaticMarketSignalProvider
from app.services.media_analysis_service import MediaAnalysisService
from app.services.media_status_service import MediaStatusService
from app.services.media_tagging_service import MediaTaggingService
from app.services.topic_selection_service import TopicSelectionService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def _build_service() -> TopicSelectionService:
    return TopicSelectionService(
        market_provider=StaticMarketSignalProvider(),
        media_analysis_service=MediaAnalysisService(
            tagging_service=MediaTaggingService(),
            status_service=MediaStatusService(),
        ),
    )


def main() -> None:
    """Точка входа CLI контент-плана."""
    parser = argparse.ArgumentParser(description="Недельный контент-план проекта")
    parser.add_argument("--project-slug", default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--weeks", type=int, default=1)
    parser.add_argument("--posts-per-week", type=int, default=3)
    parser.add_argument("--business-priority", action="append", default=None)
    args = parser.parse_args()

    if not args.project_slug and args.project_id is None:
        print("Укажите --project-slug или --project-id.")
        return

    request = TopicSelectionRequest(
        business_priorities=parse_business_priorities(args.business_priority) or None,
        weeks=args.weeks,
        posts_per_week=args.posts_per_week,
    )

    service = _build_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if args.project_id is not None:
                plan = service.build_weekly_content_plan(db, args.project_id, request)
            else:
                plan = service.build_weekly_content_plan_by_slug(db, args.project_slug, request)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return

    print(f"Контент-план: {plan.project_slug} (id={plan.project_id})")
    print(f"Недель: {plan.weeks}, публикаций в неделю: {plan.posts_per_week}\n")
    for item in plan.items:
        flag = " [нужна досъёмка]" if item.needs_media else ""
        print(
            f"Неделя {item.week_number}, {item.suggested_day} "
            f"[{item.recommended_format}]{flag}: {item.topic_title}"
        )
        print(f"        {item.explanation}")
    if plan.warnings:
        print("\nПредупреждения:")
        for warning in plan.warnings:
            print(f"  ! {warning}")


if __name__ == "__main__":
    main()
