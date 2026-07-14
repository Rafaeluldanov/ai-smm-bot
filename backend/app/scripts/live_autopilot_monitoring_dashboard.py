"""CLI дашборда мониторинга live-автопилота — v0.6.1.

Запуск:
  make live-autopilot-monitoring-dashboard project_id=1
  python -m app.scripts.live_autopilot_monitoring_dashboard --project-id 1

Показывает здоровье автопилота, инциденты и состояние стоп-крана. Ничего не публикует,
глобальные live-флаги не трогает, секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.live_autopilot_monitoring_service import (
    get_live_autopilot_monitoring_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов дашборда мониторинга."""
    parser = argparse.ArgumentParser(description="Дашборд мониторинга автопилота")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI дашборда мониторинга."""
    args = build_parser().parse_args()
    service = get_live_autopilot_monitoring_service()
    factory = get_sessionmaker()
    with factory() as db:
        d = service.build_dashboard(db, args.project_id)
    s = d["snapshot"]
    ks = d["kill_switch"]
    print(f"health:              {d['health_status']} ({d['health_label']})")
    print(f"attempts (period):   {s['total_attempts']}")
    print(f"published/failed:    {s['published_count']}/{s['failed_count']}")
    print(f"failure_rate:        {s['failure_rate']}")
    print(
        f"open_incidents:      {d['open_incident_count']} (critical {d['critical_incident_count']})"
    )
    print(f"autopilot_paused:    {ks['autopilot_paused']}")
    print(f"project_live:        {ks['project_live_enabled']}")
    print(f"can_publish_live:    {ks['can_publish_live']}")
    for blocker in d["blockers"]:
        print(f"  blocker {blocker['type']}: {blocker['message']}")
    print("Мониторинг только наблюдает; условия публикации не меняются.")


if __name__ == "__main__":
    main()
