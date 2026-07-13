"""CLI симуляции входящего Telegram-апдейта (``/start <token>``) — sandbox, без сети.

Запуск:
  make telegram-update-simulate token=TOKEN chat_id=123456 username=user
  python -m app.scripts.telegram_update_simulate --token TOKEN --chat-id 123456 [--username user]

Прогоняет фейковый апдейт через incoming-сервис (парсинг + авто-верификация /start). Реального
Telegram нет. chat_id/token по умолчанию МАСКИРУЮТСЯ (сырые — только при --show-unsafe true).
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.telegram_incoming_service import get_telegram_incoming_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов симуляции апдейта."""
    parser = argparse.ArgumentParser(description="Симуляция входящего Telegram-апдейта (sandbox)")
    parser.add_argument("--token", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--telegram-user-id", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--update-id", type=int, default=None)
    parser.add_argument(
        "--show-unsafe",
        default="false",
        help="true → показать сырой chat_id/token (по умолчанию masked)",
    )
    return parser


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _mask(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def main() -> None:
    """Точка входа CLI симуляции апдейта."""
    args = build_parser().parse_args()
    unsafe = _truthy(args.show_unsafe)
    service = get_telegram_incoming_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.simulate_update(
            db,
            args.token,
            args.chat_id,
            telegram_user_id=args.telegram_user_id,
            username=args.username,
            update_id=args.update_id,
        )
    print(f"status:  {result.get('status')}")
    print(f"ok:      {result.get('ok')}")
    if result.get("chat_id_masked"):
        print(f"chat_id (masked): {result['chat_id_masked']}")
    else:
        print(f"chat_id (masked): {_mask(args.chat_id)}")
    if unsafe:
        print(f"chat_id (RAW — не логировать): {args.chat_id}")
    print("Реального Telegram нет; это sandbox-симуляция.")


if __name__ == "__main__":
    main()
