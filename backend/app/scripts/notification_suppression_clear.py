"""CLI снятия подавления (suppression) (по умолчанию dry-run — без записи).

Запуск:
  make notification-suppression-clear suppression_id=1 dry_run=true
  python -m app.scripts.notification_suppression_clear --suppression-id 1 --dry-run false

Снимает подавление ТОЛЬКО при --dry-run false. Секреты/адреса не печатаются.
"""

import argparse

from app.api.deps import get_notification_suppression_service
from app.db.session import get_sessionmaker
from app.repositories import notification_safety_repository as safety_repo


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов снятия подавления."""
    parser = argparse.ArgumentParser(description="Снять подавление (dry-run по умолчанию)")
    parser.add_argument("--suppression-id", type=int, required=True)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI снятия подавления."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_notification_suppression_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            row = safety_repo.get_suppression_by_id(db, args.suppression_id)
            if row is None:
                print(f"DRY-RUN: подавление #{args.suppression_id} не найдено")
                return
            print(
                f"DRY-RUN снятие: подавление #{args.suppression_id} · "
                f"канал {row.channel} · статус {row.status}"
            )
            return
        result = service.clear_suppression(db, args.suppression_id)
        print(f"Подавление #{args.suppression_id}: {result['status']} · канал {result['channel']}")


if __name__ == "__main__":
    main()
