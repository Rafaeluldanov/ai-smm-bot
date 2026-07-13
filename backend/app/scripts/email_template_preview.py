"""CLI предпросмотра email-шаблона на демо-данных (read-only, sandbox).

Запуск:
  make email-template-preview template_type=review_assigned
  python -m app.scripts.email_template_preview --template-type digest_daily

Печатает subject/text/html-предпросмотр. Реальной отправки нет; unsubscribe-URL — плейсхолдер.
Секреты/SMTP-пароль/сырые токены не печатаются.
"""

import argparse

from app.api.deps import get_email_template_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра email-шаблона."""
    parser = argparse.ArgumentParser(description="Предпросмотр email-шаблона (sandbox)")
    parser.add_argument("--template-type", default="system_notice")
    parser.add_argument("--list", action="store_true", help="Показать доступные типы шаблонов")
    return parser


def main() -> None:
    """Точка входа CLI предпросмотра email-шаблона."""
    args = build_parser().parse_args()
    service = get_email_template_service()
    if args.list:
        for tpl in service.list_available_templates():
            print(f"{tpl['template_type']:32} · {tpl['status']:8} · {tpl['purpose']}")
        return
    result = service.preview_template(args.template_type)
    print(f"тип:      {args.template_type}")
    print(f"subject:  {result['subject']}")
    print("--- text ---")
    print(result["text_body"])
    print("--- html (предпросмотр) ---")
    print(result["html_body"])
    print("Реальной email-отправки нет; это sandbox-предпросмотр.")


if __name__ == "__main__":
    main()
