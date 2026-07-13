"""CLI верификации привязки Telegram (ручная, для MVP/локально; без сети).

Запуск:
  make telegram-binding-verify token=TOKEN chat_id=123456 username=user
  python -m app.scripts.telegram_binding_verify --token TOKEN --chat-id 123456 [--username user]

chat_id сохраняется зашифрованно; наружу печатается только МАСКОЙ (если не задан --show-unsafe).
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.notification_telegram_binding_service import (
    get_notification_telegram_binding_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов верификации привязки Telegram."""
    parser = argparse.ArgumentParser(description="Верифицировать привязку Telegram (dry/локально)")
    parser.add_argument("--token", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--telegram-user-id", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument(
        "--show-unsafe",
        default="false",
        help="true → показать сырой chat_id (по умолчанию masked)",
    )
    return parser


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> None:
    """Точка входа CLI верификации привязки Telegram."""
    args = build_parser().parse_args()
    service = get_notification_telegram_binding_service()
    factory = get_sessionmaker()
    with factory() as db:
        view = service.verify_binding_token(
            db,
            args.token,
            args.chat_id,
            telegram_user_id=args.telegram_user_id,
            username=args.username,
        )
    print(f"binding_id: {view['id']}")
    print(f"status:     {view['status']}")
    print(f"verified:   {view['verified']}")
    if _truthy(args.show_unsafe):
        print(f"chat_id (RAW — не логировать): {args.chat_id}")
    else:
        print(f"chat_id (masked): {view['chat_id_masked']}")
    print("Реальной Telegram-доставки нет; это sandbox.")


if __name__ == "__main__":
    main()
