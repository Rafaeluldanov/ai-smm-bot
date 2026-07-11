"""CLI пересчёта профиля обучения по метрикам (по умолчанию dry-run — без списания).

Запуск:
  make learning-rebuild project_id=1 dry_run=true
  python -m app.scripts.rebuild_learning_from_metrics --project-id 1 --dry-run true
"""

import argparse

from app.api.deps import get_metrics_import_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов пересчёта обучения по метрикам."""
    parser = argparse.ArgumentParser(
        description="Пересчёт обучения по метрикам (dry-run по умолчанию)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--depth", default="standard", help="light|standard|deep")
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI пересчёта обучения по метрикам."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_metrics_import_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.rebuild_learning_from_metrics(
            db,
            args.project_id,
            _platform(args.platform),
            depth=args.depth,
            dry_run=dry_run,
        )
    mode = "DRY-RUN (без списания)" if result["dry_run"] else "запись"
    print(f"Пересчёт обучения по метрикам [{mode}]: проект {result['project_id']}")
    print(f"  версия профиля: {result['profile_version']}")
    print(f"  уверенность: {round(result['confidence_score'] * 100)}%")
    print(f"  списано units: {result['units_charged']}")
    for change in result["changes"]:
        print(f"  • {change}")


if __name__ == "__main__":
    main()
