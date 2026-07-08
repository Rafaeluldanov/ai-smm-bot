"""CLI: ручное пополнение депозита аккаунта (units, fake-провайдер).

Реальных платежей нет. Идемпотентно по ``--idempotency-key``.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.billing_topup --account-id 1 --units 500
"""

import argparse

from app.api.deps import get_billing_service
from app.db.session import get_sessionmaker
from app.services.billing_service import BillingError


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов пополнения."""
    parser = argparse.ArgumentParser(description="Ручное пополнение депозита (units)")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--units", type=int, required=True)
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--description", default="Ручное пополнение (CLI)")
    return parser


def main() -> None:
    """Точка входа CLI пополнения."""
    args = build_parser().parse_args()
    service = get_billing_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            entry = service.manual_topup(
                db, args.account_id, args.units, args.idempotency_key, args.description
            )
        except BillingError as exc:
            print(f"Ошибка: {exc}")
            return
    print(
        f"Пополнение аккаунта {args.account_id}: +{entry.amount_units} units "
        f"(баланс {entry.balance_after_units} units)"
    )


if __name__ == "__main__":
    main()
