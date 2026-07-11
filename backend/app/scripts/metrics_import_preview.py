"""CLI превью импорта метрик (без записи и без списания units).

Запуск:
  make metrics-import-preview project_id=1 platform=telegram source=demo depth=standard
  python -m app.scripts.metrics_import_preview --project-id 1 --platform telegram \
      --source demo --depth standard
"""

import argparse

from app.api.deps import get_metrics_import_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов превью импорта метрик."""
    parser = argparse.ArgumentParser(description="Превью импорта метрик (без записи)")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--source", default="demo", help="demo|manual|estimated|internal|api")
    parser.add_argument("--depth", default="standard", help="light|standard|deep")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI превью импорта метрик."""
    args = build_parser().parse_args()
    service = get_metrics_import_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.preview_import(
            db,
            args.project_id,
            _platform(args.platform),
            args.source,
            depth=args.depth,
        )
    print(
        f"Превью импорта метрик: проект {result['project_id']}, источник {result['source']}, "
        f"глубина {result['depth']}"
    )
    print(f"  публикаций найдено: {result['publications_found']}")
    print(f"  оценка списания: {result['estimated_units']} units")
    for row in result["per_platform"]:
        print(
            f"  {row['platform']}: статус {row['status']}, "
            f"api_enabled={row['api_enabled']}, доступно {row['publications_available']}"
        )
    for warning in result["warnings"]:
        print(f"  ⚠ {warning}")


if __name__ == "__main__":
    main()
