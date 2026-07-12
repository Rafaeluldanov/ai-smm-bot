"""CLI предпросмотра доставки уведомления (read-only, без записи).

Запуск:
  make notification-delivery-preview notification_id=1 channels=email,telegram
  python -m app.scripts.notification_delivery_preview --notification-id 1 --channels email

Печатает провайдера и MASKED destination. Секреты/токены не печатаются; внешней доставки нет.
"""

import argparse

from app.api.deps import get_notification_delivery_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра доставки."""
    parser = argparse.ArgumentParser(description="Предпросмотр доставки уведомления")
    parser.add_argument("--notification-id", type=int, required=True)
    parser.add_argument(
        "--channels", default="email", help="email,telegram,webhook (через запятую)"
    )
    return parser


def _channels(value: str) -> list[str]:
    return [c.strip() for c in str(value or "email").split(",") if c.strip()]


def main() -> None:
    """Точка входа CLI предпросмотра доставки."""
    args = build_parser().parse_args()
    service = get_notification_delivery_service()
    factory = get_sessionmaker()
    with factory() as db:
        for channel in _channels(args.channels):
            pv = service.preview_delivery(db, args.notification_id, channel)
            print(
                f"канал {pv['channel']} · провайдер {pv['provider']} · "
                f"назначение {pv['destination_masked']} · внешняя доставка: "
                f"{'вкл' if pv['external_delivery_enabled'] else 'выкл'}"
            )
            for reason in pv["disabled_reasons"]:
                print(f"  — {reason}")
    print("  Реальной отправки нет; destination только маской.")


if __name__ == "__main__":
    main()
