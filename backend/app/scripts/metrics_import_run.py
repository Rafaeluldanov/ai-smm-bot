"""CLI импорта метрик (по умолчанию dry-run — без записи и без списания).

Запуск:
  make metrics-import-run project_id=1 platform=telegram source=demo depth=standard dry_run=true
  python -m app.scripts.metrics_import_run --project-id 1 --platform telegram \
      --source demo --depth standard --dry-run true

Реальные внешние API выключены по умолчанию; demo-импорт бесплатен.
"""

import argparse

from app.api.deps import get_metrics_import_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов импорта метрик."""
    parser = argparse.ArgumentParser(description="Импорт метрик (dry-run по умолчанию)")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--source", default="demo", help="demo|manual|estimated|internal|api")
    parser.add_argument("--depth", default="standard", help="light|standard|deep")
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    parser.add_argument("--idempotency-key", default=None)
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI импорта метрик."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_metrics_import_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            result = service.run_import_dry(
                db, args.project_id, _platform(args.platform), args.source, depth=args.depth
            )
            print(
                f"DRY-RUN импорта метрик: проект {result['project_id']}, "
                f"источник {result['source']}"
            )
            print(f"  публикаций найдено: {result['publications_found']}")
            print(f"  оценка списания: {result['estimated_units']} units (не списано)")
        else:
            result = service.run_import(
                db,
                args.project_id,
                _platform(args.platform),
                args.source,
                depth=args.depth,
                idempotency_key=args.idempotency_key,
            )
            print(f"Импорт метрик: статус {result.get('status') or result.get('outcome')}")
            print(f"  публикаций просканировано: {result.get('publications_scanned', 0)}")
            print(f"  снимков создано: {result.get('snapshots_created', 0)}")
            print(f"  сигналов обучения: {result.get('learning_events_created', 0)}")
            print(f"  списано units: {result.get('units_charged', 0)}")


if __name__ == "__main__":
    main()
