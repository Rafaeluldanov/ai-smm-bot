"""CLI предпросмотра email для конкретного уведомления/дайджеста (read-only, sandbox).

Запуск:
  make email-notification-preview notification_id=1
  make email-notification-preview digest_id=1
  python -m app.scripts.email_notification_preview --notification-id 1 [--show-unsafe-url true]

По умолчанию unsubscribe-URL МАСКИРОВАН. Полный URL с сырым токеном печатается ТОЛЬКО при
--show-unsafe-url true (для отладки; в логи/аудит сырой токен не попадает). Реальной отправки нет.
"""

import argparse

from app.api.deps import get_email_template_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра email уведомления/дайджеста."""
    parser = argparse.ArgumentParser(description="Предпросмотр email уведомления (sandbox)")
    parser.add_argument("--notification-id", type=int, default=None)
    parser.add_argument("--digest-id", type=int, default=None)
    parser.add_argument(
        "--show-unsafe-url",
        default="false",
        help="true → показать полный unsubscribe-URL с сырым токеном (по умолчанию masked)",
    )
    return parser


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> None:
    """Точка входа CLI предпросмотра email уведомления/дайджеста."""
    args = build_parser().parse_args()
    if args.notification_id is None and args.digest_id is None:
        raise SystemExit("Укажите --notification-id или --digest-id")
    reveal = _truthy(args.show_unsafe_url)
    service = get_email_template_service()
    factory = get_sessionmaker()
    with factory() as db:
        if args.digest_id is not None:
            result = service.render_digest_email(db, args.digest_id)
        else:
            result = service.render_notification_email(
                db, args.notification_id, reveal_unsubscribe=reveal
            )
    print(f"subject:  {result['subject']}")
    print("--- text ---")
    print(result["text_body"])
    unsub = result.get("unsubscribe_url_masked") or result.get("unsubscribe_url", "")
    if unsub:
        print(
            f"unsubscribe: {unsub}{'  (СЫРОЙ ТОКЕН — не логировать)' if reveal else '  (masked)'}"
        )
    print("Реальной email-отправки нет; это sandbox-предпросмотр.")


if __name__ == "__main__":
    main()
