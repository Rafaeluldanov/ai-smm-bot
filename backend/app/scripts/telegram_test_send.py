"""CLI тестовой Telegram-отправки (DRY-RUN only, sandbox).

Запуск:
  make telegram-test-send user_id=1 template_type=system_notice dry_run=true
  python -m app.scripts.telegram_test_send --user-id 1 --template-type system_notice --dry-run true

Реальной Telegram-отправки НЕТ ни при каких условиях в этом скрипте — только рендер/предпросмотр
и проверка safety-гейтов. chat_id печатается МАСКОЙ; bot token / сырые токены не печатаются.
"""

import argparse

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.services.notification_telegram_binding_service import (
    get_notification_telegram_binding_service,
)
from app.services.telegram_notification_template_service import (
    get_telegram_notification_template_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов тестовой Telegram-отправки."""
    parser = argparse.ArgumentParser(description="Тестовая Telegram-отправка (dry-run/sandbox)")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--template-type", default="system_notice")
    parser.add_argument(
        "--dry-run", default="true", help="Всегда dry-run в MVP (реальной отправки нет)"
    )
    return parser


def main() -> None:
    """Точка входа CLI тестовой Telegram-отправки (dry-run)."""
    args = build_parser().parse_args()
    settings = get_settings()
    tpl = get_telegram_notification_template_service()
    binding_service = get_notification_telegram_binding_service()
    factory = get_sessionmaker()
    with factory() as db:
        binding = binding_service.get_active_binding(db, args.user_id)
        dest_masked = binding.chat_id_masked if binding is not None else "—"
        preview = tpl.preview_template(args.template_type, {"user_name": "Тест"})

    live_flag = "вкл" if settings.notification_telegram_live_send_enabled_effective else "выкл"
    test_flag = "вкл" if settings.notification_telegram_test_send_enabled_effective else "выкл"
    print(f"получатель (masked): {dest_masked}")
    print(f"verified binding: {binding is not None}")
    print(f"NOTIFICATION_TELEGRAM_TEST_SEND_ENABLED: {test_flag}")
    print(f"Telegram live: {live_flag}")
    if not settings.notification_telegram_test_send_enabled_effective:
        print("БЛОКИРОВАНО: тестовая отправка выключена")
        print("(NOTIFICATION_TELEGRAM_TEST_SEND_ENABLED=false). Показан только предпросмотр.")
    print(f"subject: {preview['subject']}")
    print("--- text ---")
    print(preview["text"])
    print("Реальной Telegram-отправки нет; это dry-run/sandbox.")


if __name__ == "__main__":
    main()
