"""CLI предпросмотра дайджеста уведомлений (read-only, без записи).

Запуск:
  make notification-digest-preview user_id=1 frequency=daily
  python -m app.scripts.notification_digest_preview --user-id 1 --frequency daily

Секреты/пути не печатаются; реальной отправки нет.
"""

import argparse

from app.api.deps import get_notification_digest_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра дайджеста."""
    parser = argparse.ArgumentParser(description="Предпросмотр дайджеста уведомлений")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--frequency", default="daily", help="daily|weekly")
    return parser


def main() -> None:
    """Точка входа CLI предпросмотра дайджеста."""
    args = build_parser().parse_args()
    service = get_notification_digest_service()
    factory = get_sessionmaker()
    with factory() as db:
        preview = service.preview_digest(db, args.user_id, frequency=args.frequency)
    print(f"Дайджест ({preview['frequency']}) для пользователя #{preview['user_id']}")
    print(f"  тема: {preview['subject']}")
    print(
        f"  уведомлений: {preview['notification_count']} · дайджесты: "
        f"{'вкл' if preview['digest_enabled'] else 'выкл'} · внешняя доставка: "
        f"{'вкл' if preview['external_delivery_enabled'] else 'выкл'}"
    )
    print("  Реальной отправки нет; секреты не печатаются.")


if __name__ == "__main__":
    main()
