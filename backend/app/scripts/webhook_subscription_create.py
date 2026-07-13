"""CLI создания webhook-подписки (по умолчанию dry-run — без записи).

Запуск:
  make webhook-subscription-create account_id=1 url=https://hooks.example.com/x dry_run=true
  python -m app.scripts.webhook_subscription_create --account-id 1 --url https://... --dry-run false

Пишет ТОЛЬКО при --dry-run false. URL/secret шифруются; в выводе URL только маской.
"""

import argparse

from app.api.deps import get_webhook_subscription_service
from app.db.session import get_sessionmaker
from app.services.webhook_subscription_service import mask_url


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания подписки."""
    parser = argparse.ArgumentParser(description="Создать webhook-подписку (dry-run по умолчанию)")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", default="webhook")
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI создания подписки."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_webhook_subscription_service()
    factory = get_sessionmaker()
    if dry_run:
        print(
            f"DRY-RUN webhook-подписка: account #{args.account_id} · "
            f"URL {mask_url(args.url)} (без записи)"
        )
        print("  Signing secret был бы сгенерирован и сохранён зашифрованно.")
        return
    with factory() as db:
        result = service.create_subscription(
            db, args.account_id, args.title, args.url, project_id=args.project_id
        )
    print(
        f"Подписка #{result['id']} создана: {result['url_masked']} · "
        f"secret {result['signing_secret_masked']}"
    )
    print("  Сырой URL/secret не выводятся; реальный вызов выключен.")


if __name__ == "__main__":
    main()
