"""CLI создания привязки Telegram (verification token показывается ОДИН раз).

Запуск:
  make telegram-binding-create user_id=1
  python -m app.scripts.telegram_binding_create --user-id 1 [--project-id 1] [--account-id 1]

Печатает команду ``/start <token>`` для бота. Токен — единоразовый; в лог целиком не пишется.
Bot token / chat_id не печатаются (chat_id ещё нет — привязка pending).
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.notification_telegram_binding_service import (
    get_notification_telegram_binding_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания привязки Telegram."""
    parser = argparse.ArgumentParser(description="Создать привязку Telegram (verification token)")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--title", default=None)
    return parser


def main() -> None:
    """Точка входа CLI создания привязки Telegram."""
    args = build_parser().parse_args()
    service = get_notification_telegram_binding_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.create_binding_token(
            db,
            args.user_id,
            account_id=args.account_id,
            project_id=args.project_id,
            title=args.title,
        )
    print(f"binding_id: {result['binding_id']}")
    print(f"status:     {result['status']}")
    print(f"token prefix: {result['verification_token_prefix']}")
    print("Отправьте боту команду (показывается один раз):")
    print(f"  {result['bot_command']}")
    for step in result["instructions"]:
        print(f"  - {step}")
    print("Реальной Telegram-доставки нет; это sandbox.")


if __name__ == "__main__":
    main()
