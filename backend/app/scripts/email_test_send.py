"""CLI тестовой отправки email (DRY-RUN only, sandbox).

Запуск:
  make email-test-send to=user@example.ru template_type=system_notice
  python -m app.scripts.email_test_send --to user@example.ru --template-type digest_daily

Реальной SMTP-отправки НЕТ ни при каких условиях в этом скрипте — только рендер/предпросмотр
и проверка safety-гейтов. Получатель печатается МАСКОЙ; SMTP-пароль/сырые токены не печатаются.
"""

import argparse

from app.api.deps import get_email_template_service
from app.config import get_settings
from app.services.notification_delivery import mask_destination


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов тестовой отправки email."""
    parser = argparse.ArgumentParser(description="Тестовая отправка email (dry-run/sandbox)")
    parser.add_argument("--to", required=True, help="Email получателя (печатается маской)")
    parser.add_argument("--template-type", default="system_notice")
    return parser


def main() -> None:
    """Точка входа CLI тестовой отправки email (dry-run)."""
    args = build_parser().parse_args()
    settings = get_settings()
    service = get_email_template_service()
    to_masked = mask_destination("email", args.to)
    allowed = settings.email_test_allowed_recipients_list

    test_flag = "вкл" if settings.email_test_send_enabled_effective else "выкл"
    live_flag = "вкл" if settings.smtp_live_send_enabled_effective else "выкл"
    print(f"получатель (masked): {to_masked}")
    print(f"EMAIL_TEST_SEND_ENABLED: {test_flag}")
    print(f"SMTP live: {live_flag}")

    if not settings.email_test_send_enabled_effective:
        print("БЛОКИРОВАНО: тестовая отправка выключена (EMAIL_TEST_SEND_ENABLED=false).")
        print("Показан только предпросмотр; реальной отправки нет.")
    elif allowed and args.to.strip().lower() not in allowed:
        print("БЛОКИРОВАНО: получатель не в allowlist (EMAIL_TEST_ALLOWED_RECIPIENTS).")
        return

    preview = service.preview_template(args.template_type, {"user_name": "Тест"})
    print(f"subject: {preview['subject']}")
    print("--- text ---")
    print(preview["text_body"])
    print("Реальной email-отправки нет; это dry-run/sandbox.")


if __name__ == "__main__":
    main()
