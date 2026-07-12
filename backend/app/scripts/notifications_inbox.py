"""CLI inbox уведомлений пользователя (read-only, без записи).

Запуск:
  make notifications-inbox user_id=1 [status=unread]
  python -m app.scripts.notifications_inbox --user-id 1 --status unread

Секреты/пути к файлам не печатаются; внешней доставки нет.
"""

import argparse

from app.api.deps import get_notification_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов inbox."""
    parser = argparse.ArgumentParser(description="Inbox уведомлений пользователя")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--status", default=None, help="unread|read|dismissed|archived (или все)")
    parser.add_argument("--limit", type=int, default=50)
    return parser


def main() -> None:
    """Точка входа CLI inbox."""
    args = build_parser().parse_args()
    service = get_notification_service()
    factory = get_sessionmaker()
    status = None if args.status in (None, "", "all") else args.status
    with factory() as db:
        inbox = service.build_user_inbox(db, args.user_id, status=status, limit=args.limit)
    print(f"Уведомления пользователя #{inbox['user_id']}")
    print(f"  непрочитанных: {inbox['unread_count']} · показано: {inbox['count']}")
    for n in inbox["notifications"]:
        print(
            f"  #{n['id']} [{n['status']}] {n['notification_type']} · "
            f"{n['priority']} · {n['title']}"
        )
    print("  Внешней доставки нет; внутренние уведомления бесплатны.")


if __name__ == "__main__":
    main()
