"""CLI генерации предложений экспериментов (по умолчанию dry-run — без записи).

Запуск:
  make experiment-suggestions-generate project_id=1 platform=telegram dry_run=true
  python -m app.scripts.experiment_suggestions_generate --project-id 1 --platform telegram \
      --dry-run true

Live-публикаций нет; генерация предложений бесплатна.
"""

import argparse

from app.api.deps import get_experiment_suggestion_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов генерации предложений."""
    parser = argparse.ArgumentParser(
        description="Генерация предложений экспериментов (dry-run по умолчанию)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI генерации предложений."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_experiment_suggestion_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            result = service.preview_suggestions(db, args.project_id, _platform(args.platform))
            print(f"DRY-RUN генерации предложений: проект {result['project_id']} (без записи)")
            print(f"  кандидатов: {len(result['suggestions'])}")
        else:
            result = service.generate_suggestions(
                db, args.project_id, _platform(args.platform), source="cli"
            )
            print(f"Генерация предложений: проект {result['project_id']}")
            print(
                f"  создано: {result['created']}, пропущено: {result['skipped']}, "
                f"просканировано: {result['scanned']}"
            )


if __name__ == "__main__":
    main()
