"""CLI списка инцидентов live-автопилота — v0.6.1.

Запуск:
  make live-autopilot-monitoring-incidents project_id=1 [status=open]
  python -m app.scripts.live_autopilot_monitoring_incidents --project-id 1 --status open

Показывает инциденты автопилота (повторные сбои, низкий баланс и т.п.). Секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.live_autopilot_monitoring_service import (
    get_live_autopilot_monitoring_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов списка инцидентов."""
    parser = argparse.ArgumentParser(description="Инциденты автопилота")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--status", type=str, default=None)
    parser.add_argument("--limit", type=int, default=50)
    return parser


def main() -> None:
    """Точка входа CLI списка инцидентов."""
    args = build_parser().parse_args()
    service = get_live_autopilot_monitoring_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.list_incidents(db, args.project_id, status=args.status, limit=args.limit)
    open_count = result["open_incident_count"]
    critical = result["critical_incident_count"]
    print(f"open_incidents:      {open_count} (critical {critical})")
    if not result["incidents"]:
        print("Инцидентов нет.")
        return
    for inc in result["incidents"]:
        print(
            f"  #{inc['id']} [{inc['severity']}] {inc['status']} {inc['incident_type']}: "
            f"{inc['title']} (x{inc['occurrences']})"
        )


if __name__ == "__main__":
    main()
