"""CLI планировщика дайджестов (по умолчанию dry-run — без записи/отправки).

Запуск:
  make notification-digest-scheduler frequency=daily dry_run=true
  python -m app.scripts.notification_digest_scheduler --frequency daily --dry-run false

Находит пользователей с включённым дайджестом; выключено по умолчанию. Реальной отправки нет.
"""

import argparse

from app.api.deps import get_notification_digest_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов планировщика."""
    parser = argparse.ArgumentParser(description="Планировщик дайджестов (dry-run по умолчанию)")
    parser.add_argument("--frequency", default="daily", help="daily|weekly")
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI планировщика дайджестов."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_notification_digest_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.run_digest_scheduler(db, frequency=args.frequency, dry_run=dry_run)
    mode = "DRY-RUN" if dry_run else "RUN"
    print(
        f"{mode} планировщик дайджестов ({result['frequency']}) · пользователей "
        f"{result['users']} · сгенерировано {result['generated']} · enabled {result['enabled']}"
    )
    print("  Реальной отправки нет; дайджесты выключены по умолчанию.")


if __name__ == "__main__":
    main()
