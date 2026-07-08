"""CLI: ручное пополнение SaaS-баланса аккаунта.

Без реальных платёжных провайдеров: создаёт ledger entry и увеличивает баланс
во внутренних units. Секреты и live-публикации не используются.
"""

import argparse

from app.api.deps import get_billing_service
from app.db.session import get_sessionmaker
from app.services.billing_service import BillingError


def build_parser() -> argparse.ArgumentParser:
    """Собрать CLI-парсер."""
    parser = argparse.ArgumentParser(description="Ручное пополнение SaaS-баланса")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--units", type=int, required=True)
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--description", default="Manual top-up")
    return parser


def main() -> None:
    """Точка входа CLI."""
    args = build_parser().parse_args()
    service = get_billing_service()

    try:
        with get_sessionmaker()() as db:
            entry = service.manual_topup(
                db,
                account_id=args.account_id,
                amount_units=args.units,
                idempotency_key=args.idempotency_key,
                description=args.description,
            )

            entry_id = entry.id
            amount_units = entry.amount_units
            balance_after_units = entry.balance_after_units

    except BillingError as exc:
        print(f"Ошибка: {exc}")
        return

    print(
        f"Пополнение аккаунта {args.account_id}: +{amount_units} units "
        f"→ баланс {balance_after_units} units "
        f"(ledger_entry_id={entry_id})"
    )


if __name__ == "__main__":
    main()
