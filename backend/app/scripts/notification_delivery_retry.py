"""CLI повтора просроченных доставок (по умолчанию dry-run — без внешней отправки).

Запуск:
  make notification-delivery-retry dry_run=true
  python -m app.scripts.notification_delivery_retry --dry-run false

Повторяет pending/retry_scheduled с backoff и лимитом попыток. Внешней доставки нет; секреты
не печатаются.
"""

import argparse

from app.api.deps import get_notification_delivery_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов повтора."""
    parser = argparse.ArgumentParser(description="Повтор доставок (dry-run по умолчанию)")
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    parser.add_argument("--limit", type=int, default=100)
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI повтора доставок."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_notification_delivery_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.retry_due_deliveries(db, dry_run=dry_run, limit=args.limit)
    mode = "DRY-RUN" if dry_run else "SANDBOX"
    print(
        f"{mode} повтор доставок · обработано: {result['retried']} · enabled: {result['enabled']}"
    )
    print("  Внешней доставки нет; секреты не печатаются.")


if __name__ == "__main__":
    main()
