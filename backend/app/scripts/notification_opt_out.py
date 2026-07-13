"""CLI создания отписки (opt-out) (по умолчанию dry-run — без записи).

Запуск:
  make notification-opt-out user_id=1 scope=channel channel=email dry_run=true
  python -m app.scripts.notification_opt_out --user-id 1 --scope channel --channel email

Пишет отписку ТОЛЬКО при --dry-run false. Секреты не печатаются.
"""

import argparse

from app.api.deps import get_notification_unsubscribe_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отписки."""
    parser = argparse.ArgumentParser(description="Создать отписку (dry-run по умолчанию)")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument(
        "--scope", default="global", help="global|account|project|notification_type|channel"
    )
    parser.add_argument("--channel", default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--notification-type", default=None)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI отписки."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_notification_unsubscribe_service()
    factory = get_sessionmaker()
    if dry_run:
        print(
            f"DRY-RUN отписка: user #{args.user_id} · scope {args.scope} · "
            f"channel {args.channel or '—'} (без записи)"
        )
        return
    with factory() as db:
        result = service.create_opt_out(
            db,
            args.user_id,
            args.scope,
            channel=args.channel,
            project_id=args.project_id,
            notification_type=args.notification_type,
        )
    print(f"Отписка #{result['id']} создана: scope {result['scope']} · channel {result['channel']}")


if __name__ == "__main__":
    main()
