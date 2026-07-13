"""CLI предпросмотра Telegram-текста уведомления/дайджеста (read-only, sandbox).

Запуск:
  make telegram-notification-preview notification_id=1
  python -m app.scripts.telegram_notification_preview --notification-id 1
  python -m app.scripts.telegram_notification_preview --digest-id 1

Печатает subject/text/parse_mode. Реальной отправки нет; секретов/сырых токенов нет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.telegram_notification_template_service import (
    get_telegram_notification_template_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра Telegram-уведомления."""
    parser = argparse.ArgumentParser(description="Предпросмотр Telegram-текста (sandbox)")
    parser.add_argument("--notification-id", type=int, default=None)
    parser.add_argument("--digest-id", type=int, default=None)
    parser.add_argument("--template-type", default=None)
    parser.add_argument("--list", action="store_true", help="Показать доступные типы шаблонов")
    return parser


def main() -> None:
    """Точка входа CLI предпросмотра Telegram-уведомления."""
    args = build_parser().parse_args()
    service = get_telegram_notification_template_service()
    if args.list:
        for tpl in service.list_available_templates():
            print(f"{tpl['template_type']:32} · {tpl['status']:8} · {tpl['purpose']}")
        return
    if args.notification_id is None and args.digest_id is None:
        raise SystemExit("Укажите --notification-id, --digest-id или --list")
    factory = get_sessionmaker()
    with factory() as db:
        if args.digest_id is not None:
            result = service.render_digest_telegram(db, args.digest_id)
        else:
            result = service.render_notification_telegram(
                db, args.notification_id, template_type=args.template_type
            )
    print(f"subject:    {result['subject']}")
    print(f"parse_mode: {result['parse_mode']}")
    print("--- text ---")
    print(result["text"])
    print("Реальной Telegram-отправки нет; это sandbox-предпросмотр.")


if __name__ == "__main__":
    main()
