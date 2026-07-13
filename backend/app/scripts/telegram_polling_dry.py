"""CLI предпросмотра polling Telegram (getUpdates dry-run) — sandbox, без сети.

Запуск:
  make telegram-polling-dry limit=10
  python -m app.scripts.telegram_polling_dry --limit 10 [--offset 0]

По умолчанию dry-run: реального getUpdates нет. Bot token не печатается.
"""

import argparse

from app.services.telegram_bot_management_service import (
    get_telegram_bot_management_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов polling-dry."""
    parser = argparse.ArgumentParser(description="getUpdates (dry-run, sandbox)")
    parser.add_argument("--offset", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI polling-dry."""
    args = build_parser().parse_args()
    service = get_telegram_bot_management_service()
    result = service.poll_updates_dry(offset=args.offset, limit=args.limit)
    payload = result["would_send"]
    print(f"method:       {result['method']} (dry_run={result['dry_run']})")
    print(f"offset:       {payload['offset']}")
    print(f"limit:        {payload['limit']}")
    print(f"live_enabled: {result['live_enabled']}")
    print("Реального вызова Telegram API нет; это dry-run/sandbox.")


if __name__ == "__main__":
    main()
