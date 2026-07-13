"""CLI предпросмотра webhook Telegram (getWebhookInfo dry-run) — sandbox, без сети.

Запуск:
  make telegram-webhook-info dry_run=true
  python -m app.scripts.telegram_webhook_info --dry-run true

По умолчанию dry-run: реального вызова Telegram API нет. Bot token / secret не печатаются.
"""

import argparse

from app.services.telegram_bot_management_service import (
    get_telegram_bot_management_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов webhook-info."""
    parser = argparse.ArgumentParser(description="getWebhookInfo (dry-run, sandbox)")
    parser.add_argument(
        "--dry-run", default="true", help="Всегда dry-run в MVP (реального вызова нет)"
    )
    return parser


def main() -> None:
    """Точка входа CLI webhook-info (dry-run)."""
    build_parser().parse_args()
    service = get_telegram_bot_management_service()
    preview = service.preview_webhook_setup()
    info = service.get_webhook_info_dry()
    print(f"webhook_url:       {preview['webhook_url']}")
    print(f"secret_required:   {preview['secret_required']}")
    print(f"secret_configured: {preview['secret_configured']}")
    print(f"live_enabled:      {preview['live_enabled']}")
    print(f"method:            {info['method']} (dry_run={info['dry_run']})")
    print("Реального вызова Telegram API нет; это dry-run/sandbox.")


if __name__ == "__main__":
    main()
