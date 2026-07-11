"""CLI выбора winner эксперимента (по умолчанию dry-run — без записи/списания).

Запуск:
  make experiment-winner experiment_id=1 method=auto dry_run=true
  python -m app.scripts.choose_experiment_winner --experiment-id 1 --method auto --dry-run true
"""

import argparse

from app.api.deps import get_ab_testing_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов выбора winner."""
    parser = argparse.ArgumentParser(
        description="Выбрать winner эксперимента (dry-run по умолчанию)"
    )
    parser.add_argument("--experiment-id", type=int, required=True)
    parser.add_argument("--method", default="auto", help="auto|manual")
    parser.add_argument("--variant-id", type=int, default=None)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI выбора winner."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_ab_testing_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            summary = service.build_experiment_summary(db, args.experiment_id)
            ranked = summary["ranking"]
            print(
                f"DRY-RUN выбор winner эксперимента #{args.experiment_id} "
                "(без записи, без списания)"
            )
            if ranked:
                top = ranked[0]
                print(f"  предполагаемый winner: {top['variant_key']} (score {top['score']})")
            else:
                print("  вариантов нет")
            return
        result = service.choose_winner(
            db, args.experiment_id, method=args.method, variant_id=args.variant_id
        )
        winner = result.get("winner") or {}
        print(f"Winner эксперимента #{args.experiment_id}: {winner.get('variant_key')}")
        print(f"  причина: {winner.get('winner_reason')}, статус: {result['experiment']['status']}")


if __name__ == "__main__":
    main()
