"""CLI создания A/B-эксперимента по теме (по умолчанию dry-run — без записи/списания).

Запуск:
  make ab-experiment-preview project_id=1 platform=telegram topic="Футболки"
  make ab-experiment-create project_id=1 platform=telegram topic="Футболки" dry_run=false
  python -m app.scripts.create_ab_experiment --project-id 1 --platform telegram \
      --topic "Футболки с логотипом для мероприятий" --variant-count 2 --dry-run true

Live-публикаций нет; варианты идут в очередь ревью.
"""

import argparse

from app.api.deps import get_ab_testing_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания A/B-эксперимента."""
    parser = argparse.ArgumentParser(
        description="Создать A/B-эксперимент по теме (dry-run по умолчанию)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--variant-count", type=int, default=2)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    parser.add_argument("--idempotency-key", default=None)
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI создания A/B-эксперимента."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_ab_testing_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            result = service.preview_topic(
                db, args.project_id, _platform(args.platform), args.topic, args.variant_count
            )
            print(f"DRY-RUN A/B по теме «{args.topic}» (без записи, без списания)")
            print(
                f"  вариантов: {result['variant_count']}, оценка: {result['estimated_units']} units"
            )
            for variant in result["variants"]:
                print(f"  {variant['variant_key']}: {variant['title']}")
        else:
            result = service.create_experiment_from_topic(
                db,
                args.project_id,
                _platform(args.platform),
                args.topic,
                variant_count=args.variant_count,
                idempotency_key=args.idempotency_key,
            )
            exp = result["experiment"]
            print(f"Эксперимент #{exp['id']} создан ({result['outcome']}). Live-публикаций нет.")
            print(f"  статус: {exp['status']}, вариантов: {len(result['variants'])}")


if __name__ == "__main__":
    main()
