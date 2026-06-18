"""Выбор тем для проекта (без сети и AI).

Запуск:
  make select-topics project_slug=teeon
  python -m app.scripts.select_topics --project-slug teeon \
      --business-priority футболки=100 --business-priority худи=80
"""

import argparse

from app.db.session import get_sessionmaker
from app.schemas.topic import TopicSelectionRequest
from app.services.market_signal_provider import StaticMarketSignalProvider
from app.services.media_analysis_service import MediaAnalysisService
from app.services.media_status_service import MediaStatusService
from app.services.media_tagging_service import MediaTaggingService
from app.services.topic_selection_service import TopicSelectionService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def parse_business_priorities(items: list[str] | None) -> dict[str, int]:
    """Разобрать аргументы вида 'футболки=100' в словарь приоритетов."""
    result: dict[str, int] = {}
    for raw in items or []:
        if "=" not in raw:
            raise ValueError(f"Неверный формат приоритета: '{raw}' (ожидается ключ=число)")
        key, _, value = raw.partition("=")
        key = key.strip()
        try:
            result[key] = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"Приоритет должен быть числом: '{raw}'") from exc
    return result


def _build_service() -> TopicSelectionService:
    return TopicSelectionService(
        market_provider=StaticMarketSignalProvider(),
        media_analysis_service=MediaAnalysisService(
            tagging_service=MediaTaggingService(),
            status_service=MediaStatusService(),
        ),
    )


def main() -> None:
    """Точка входа CLI выбора тем."""
    parser = argparse.ArgumentParser(description="Выбор тем публикаций для проекта")
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
                result = service.select_topics_for_project(db, args.project_id, request)
            else:
                result = service.select_topics_for_project_slug(db, args.project_slug, request)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return

    print(f"Проект: {result.project_slug} (id={result.project_id})")
    print(f"Кандидатов: {result.candidates_count}, выбрано: {result.selected_count}")
    print(f"Создано: {result.created}, обновлено: {result.updated}\n")
    for topic in result.topics:
        print(f"[{topic.priority_score:5.1f}] {topic.cluster} | {topic.title}")
        print(f"        {topic.explanation}")
    if result.warnings:
        print("\nПредупреждения:")
        for warning in result.warnings:
            print(f"  ! {warning}")


if __name__ == "__main__":
    main()
