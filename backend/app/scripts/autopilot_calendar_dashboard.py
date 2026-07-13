"""CLI дашборда календаря автопостинга — v0.5.8.

Запуск:
  make autopilot-calendar-dashboard project_id=1
  python -m app.scripts.autopilot_calendar_dashboard --project-id 1

Показывает активный календарь, риски, ближайшие даты и следующий шаг. Ничего не пишет,
не публикует, внешних вызовов нет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.autopilot_calendar_assistant_service import (
    get_autopilot_calendar_assistant_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов дашборда календаря."""
    parser = argparse.ArgumentParser(description="Дашборд календаря автопостинга")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI дашборда календаря."""
    args = build_parser().parse_args()
    service = get_autopilot_calendar_assistant_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.build_calendar_dashboard(db, args.project_id)
    active = result["active_plan"]
    print(f"has_active_plan: {result['has_active_plan']}")
    if active:
        print(f"preset:          {active['preset']}")
        print(f"goal:            {active['goal']}")
        print(f"status:          {active['status']}")
        print(f"weekdays:        {active['weekdays']}")
        print(f"publish_times:   {', '.join(active['publish_times'])}")
        print(f"posts_per_month: {active['estimated_posts_per_month']}")
    summary = result["simple_client_summary"]
    print(f"summary:         {summary['headline']}")
    nba = result["next_best_action"]
    print(f"next_step:       {nba['label']}")
    for risk in result["risks"]:
        print(f"  risk: {risk}")
    print(f"plans_total:     {len(result['plans'])}")


if __name__ == "__main__":
    main()
