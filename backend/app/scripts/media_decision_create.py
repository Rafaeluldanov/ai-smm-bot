"""CLI создания решения автовыбора медиа (по умолчанию dry-run — без записи).

Запуск:
  make media-decision-create project_id=1 platform=telegram plan_id=1 dry_run=true
  python -m app.scripts.media_decision_create --project-id 1 --platform telegram --dry-run true

Пост не создаётся, live-публикаций нет; публичные ссылки не создаются; секреты не печатаются.
"""

import argparse

from app.api.deps import get_media_decision_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания решения о медиа."""
    parser = argparse.ArgumentParser(
        description="Создать решение автовыбора медиа (dry-run по умолчанию)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--plan-id", type=int, default=None)
    parser.add_argument("--topic-decision-id", type=int, default=None)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI создания решения о медиа."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_media_decision_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            result = service.preview_media_decision_for_plan(
                db,
                args.project_id,
                _platform(args.platform),
                plan_id=args.plan_id,
                topic_decision_id=args.topic_decision_id,
            )
            print(f"DRY-RUN создания медиа-решения: проект {result['project_id']} (без записи)")
            print(
                f"  стратегия: {result['selected_strategy']} · "
                f"медиа: {result['selected_media_count']} · {result['confidence_score']}"
            )
            return
        result = service.create_media_decision_for_plan(
            db,
            args.project_id,
            _platform(args.platform),
            plan_id=args.plan_id,
            topic_decision_id=args.topic_decision_id,
        )
        print(f"Медиа-решение #{result['id']}: {result['outcome']}")
        print(
            f"  стратегия: {result['selected_strategy']} · источник: {result['decision_source']} · "
            f"медиа: {result['selected_media_count']}"
        )
        print("  Пост не создан, live-публикаций нет; публичные ссылки не создаются.")


if __name__ == "__main__":
    main()
