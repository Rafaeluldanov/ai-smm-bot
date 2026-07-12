"""CLI сканирования просроченных задач ревью (по умолчанию dry-run — без записи).

Запуск:
  make notifications-overdue-scan project_id=1 [dry_run=true]
  python -m app.scripts.notifications_overdue_scan --project-id 1 --dry-run false

Создаёт task_overdue уведомления ТОЛЬКО при --dry-run false. Внешней доставки нет; без секретов.
"""

import argparse

from app.api.deps import get_notification_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов скана."""
    parser = argparse.ArgumentParser(
        description="Скан просроченных задач ревью (dry-run по умолчанию)"
    )
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI скана просрочек."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_notification_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.notify_overdue_tasks(db, args.project_id, dry_run=dry_run)
    mode = "DRY-RUN" if dry_run else "WRITE"
    print(f"{mode} скан просрочек · проект: {result.get('project_id')}")
    print(
        f"  просрочено: {result.get('overdue_found')} · создано уведомлений: "
        f"{result.get('notifications_created')} · enabled: {result.get('enabled')}"
    )
    print("  Внешней доставки нет; уведомления бесплатны в MVP.")


if __name__ == "__main__":
    main()
