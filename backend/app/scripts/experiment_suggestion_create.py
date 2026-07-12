"""CLI создания A/B из предложения (по умолчанию dry-run — без записи/списания).

Запуск:
  make experiment-suggestion-create suggestion_id=1 dry_run=true
  python -m app.scripts.experiment_suggestion_create --suggestion-id 1 --dry-run true

Live-публикаций нет; варианты уйдут в очередь ревью.
"""

import argparse

from app.api.deps import get_experiment_suggestion_service
from app.db.session import get_sessionmaker
from app.repositories import experiment_suggestion_repository


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания A/B из предложения."""
    parser = argparse.ArgumentParser(
        description="Создать A/B из предложения (dry-run по умолчанию)"
    )
    parser.add_argument("--suggestion-id", type=int, required=True)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI создания A/B из предложения."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_experiment_suggestion_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            suggestion = experiment_suggestion_repository.get_by_id(db, args.suggestion_id)
            if suggestion is None:
                print(f"Предложение #{args.suggestion_id} не найдено.")
                return
            print(
                f"DRY-RUN создания A/B из предложения #{args.suggestion_id} "
                "(без записи, без списания)"
            )
            print(f"  тема: {suggestion.topic}, оценка: {suggestion.estimated_units} units")
            return
        result = service.create_experiment_from_suggestion(db, args.suggestion_id)
        print(f"A/B из предложения #{args.suggestion_id}: {result['outcome']}")
        print(f"  эксперимент #{result.get('experiment_id')}. Live-публикаций нет.")


if __name__ == "__main__":
    main()
