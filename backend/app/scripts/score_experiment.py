"""CLI скоринга вариантов эксперимента (платное действие — анализ).

Запуск:
  make experiment-score experiment_id=1
  python -m app.scripts.score_experiment --experiment-id 1
"""

import argparse

from app.api.deps import get_ab_testing_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов скоринга эксперимента."""
    parser = argparse.ArgumentParser(description="Скоринг вариантов эксперимента")
    parser.add_argument("--experiment-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI скоринга эксперимента."""
    args = build_parser().parse_args()
    service = get_ab_testing_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.score_variants(db, args.experiment_id)
    exp = result["experiment"]
    print(f"Скоринг эксперимента #{exp['id']}: статус {exp['status']}")
    for row in result["ranking"]:
        print(
            f"  {row['variant_key']}: score {row['score']} "
            f"(actual={row['has_actual_metrics']}, confidence={row['confidence']})"
        )


if __name__ == "__main__":
    main()
