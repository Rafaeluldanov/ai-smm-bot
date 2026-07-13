"""CLI предпросмотра доставки webhook (read-only, без реального вызова).

Запуск:
  make webhook-subscription-preview subscription_id=1 [notification_id=1]
  python -m app.scripts.webhook_subscription_preview --subscription-id 1

Показывает подписанный payload, который БЫЛ БЫ отправлен (без отправки). Секреты не печатаются.
"""

import argparse

from app.api.deps import get_webhook_subscription_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов preview."""
    parser = argparse.ArgumentParser(description="Preview доставки webhook (без реального вызова)")
    parser.add_argument("--subscription-id", type=int, required=True)
    parser.add_argument("--notification-id", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI preview webhook."""
    args = build_parser().parse_args()
    service = get_webhook_subscription_service()
    factory = get_sessionmaker()
    with factory() as db:
        pv = service.preview_webhook_delivery(db, args.subscription_id, args.notification_id)
    print(f"Webhook preview: подписка #{pv['subscription_id']} · {pv['url_masked']}")
    print(f"  алгоритм: {pv['signature_algorithm']} · заголовок: {pv['signature_header']}")
    print(
        f"  подпись: {pv['signature'][:24]}… · would_send: {pv['would_send']} · "
        f"live: {pv['live_enabled']}"
    )
    print("  Реального вызова нет; сырой URL/secret не печатаются.")


if __name__ == "__main__":
    main()
