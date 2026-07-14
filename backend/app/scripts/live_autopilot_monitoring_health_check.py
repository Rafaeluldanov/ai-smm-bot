"""CLI проверки здоровья live-автопилота — v0.6.1.

Запуск:
  make live-autopilot-monitoring-health-check project_id=1 [dry_run=true]
  python -m app.scripts.live_autopilot_monitoring_health_check --project-id 1 --dry-run true

Считает здоровье автопилота за окно наблюдения. По умолчанию dry-run (ничего не пишет в БД).
При dry_run=false сохраняет снимок и при необходимости заводит инциденты. Секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.live_autopilot_monitoring_service import (
    get_live_autopilot_monitoring_service,
)


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов проверки здоровья."""
    parser = argparse.ArgumentParser(description="Проверка здоровья автопилота")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--dry-run", dest="dry_run", type=str, default="true")
    return parser


def main() -> None:
    """Точка входа CLI проверки здоровья."""
    args = build_parser().parse_args()
    dry_run = _as_bool(args.dry_run)
    service = get_live_autopilot_monitoring_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.run_health_check(db, args.project_id, dry_run=dry_run)
    print(f"health:              {result['health_status']}")
    print(f"dry_run:             {result['dry_run']}")
    print(f"snapshot_created:    {result['snapshot_created']}")
    print(f"total_attempts:      {result['total_attempts']}")
    print(f"failed/failure_rate: {result['failed_count']}/{result['failure_rate']}")
    print(f"incidents_created:   {len(result['incidents_created'])}")
    ap = result.get("auto_pause") or {}
    print(
        f"auto_pause:          {ap.get('paused', False)} (previewed={ap.get('previewed', False)})"
    )
    print(result["note"])


if __name__ == "__main__":
    main()
