"""CLI доставки уведомления (по умолчанию dry-run — без внешней отправки).

Запуск:
  make notification-delivery-send notification_id=1 channels=email dry_run=true
  python -m app.scripts.notification_delivery_send --notification-id 1 --channels email

При --dry-run false используется mock-провайдер (sandbox) — наружу ничего не отправляется, пока
внешняя доставка выключена. Секреты не печатаются.
"""

import argparse

from app.api.deps import get_notification_delivery_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов доставки."""
    parser = argparse.ArgumentParser(description="Доставка уведомления (dry-run по умолчанию)")
    parser.add_argument("--notification-id", type=int, required=True)
    parser.add_argument(
        "--channels", default="email", help="email,telegram,webhook (через запятую)"
    )
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _channels(value: str) -> list[str]:
    return [c.strip() for c in str(value or "email").split(",") if c.strip()]


def main() -> None:
    """Точка входа CLI доставки."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_notification_delivery_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.send_notification(
            db, args.notification_id, channels=_channels(args.channels), dry_run=dry_run
        )
    mode = "DRY-RUN" if dry_run else "SANDBOX"
    print(f"{mode} доставка уведомления #{args.notification_id} · каналы {result['channels']}")
    for r in result["results"]:
        print(
            f"  {r['channel']}: {r['outcome']} · "
            f"{r.get('destination_masked', '')} · {r['provider']}"
        )
    print("  Внешней доставки нет (mock/sandbox); секреты не печатаются.")


if __name__ == "__main__":
    main()
