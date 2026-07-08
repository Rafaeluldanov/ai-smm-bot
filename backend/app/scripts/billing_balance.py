"""CLI: показать баланс биллинг-счёта аккаунта (units).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.billing_balance --account-id 1
"""

import argparse

from app.api.deps import get_billing_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов баланса."""
    parser = argparse.ArgumentParser(description="Баланс биллинг-счёта аккаунта")
    parser.add_argument("--account-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI баланса."""
    args = build_parser().parse_args()
    service = get_billing_service()
    factory = get_sessionmaker()
    with factory() as db:
        billing = service.get_balance(db, args.account_id)
    print(
        f"Аккаунт {args.account_id}: {billing.balance_units} units ({billing.currency}), "
        f"тариф={billing.tariff_plan_slug or '—'}, статус={billing.status}"
    )


if __name__ == "__main__":
    main()
