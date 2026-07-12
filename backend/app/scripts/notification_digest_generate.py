"""CLI генерации дайджеста уведомлений (по умолчанию dry-run — без записи).

Запуск:
  make notification-digest-generate user_id=1 frequency=daily dry_run=true
  python -m app.scripts.notification_digest_generate --user-id 1 --frequency daily --dry-run false

Пишет запись дайджеста ТОЛЬКО при --dry-run false; реальной отправки нет. Секреты не печатаются.
"""

import argparse

from app.api.deps import get_notification_digest_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов генерации дайджеста."""
    parser = argparse.ArgumentParser(description="Генерация дайджеста (dry-run по умолчанию)")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--frequency", default="daily", help="daily|weekly")
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI генерации дайджеста."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_notification_digest_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.generate_digest(
            db, args.user_id, frequency=args.frequency, dry_run=dry_run
        )
    mode = "DRY-RUN" if dry_run else "WRITE"
    print(
        f"{mode} генерация дайджеста ({result['frequency']}) для #{args.user_id} · "
        f"уведомлений {result['notification_count']} · digest_id {result.get('digest_id')}"
    )
    print("  Реальной отправки нет; секреты не печатаются.")


if __name__ == "__main__":
    main()
