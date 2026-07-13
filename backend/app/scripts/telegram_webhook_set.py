"""CLI установки webhook Telegram (setWebhook dry-run) — sandbox, без сети.

Запуск:
  make telegram-webhook-set url=https://app.example.com/notification-telegram/webhook dry_run=true
  python -m app.scripts.telegram_webhook_set --url https://app.example.com/... --dry-run true

По умолчанию dry-run: реального setWebhook нет. Bot token / secret не печатаются (только факт).
"""

import argparse

from app.services.telegram_bot_management_service import (
    get_telegram_bot_management_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов webhook-set."""
    parser = argparse.ArgumentParser(description="setWebhook (dry-run, sandbox)")
    parser.add_argument("--url", default=None, help="Публичный HTTPS webhook URL")
    parser.add_argument(
        "--dry-run", default="true", help="Всегда dry-run в MVP (реального вызова нет)"
    )
    return parser


def main() -> None:
    """Точка входа CLI webhook-set (dry-run)."""
    args = build_parser().parse_args()
    service = get_telegram_bot_management_service()
    result = service.set_webhook_dry(url=args.url)
    payload = result["would_send"]
    print(f"method:                {result['method']} (dry_run={result['dry_run']})")
    print(f"url:                   {payload['url']}")
    print(f"secret_token_provided: {payload['secret_token_provided']}")
    print(f"allowed_updates:       {payload['allowed_updates']}")
    print(f"live_enabled:          {result['live_enabled']}")
    print("Реального вызова Telegram API нет; это dry-run/sandbox.")


if __name__ == "__main__":
    main()
