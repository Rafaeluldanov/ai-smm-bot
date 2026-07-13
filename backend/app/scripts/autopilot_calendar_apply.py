"""CLI применения календаря автопостинга к автопилоту — v0.5.8.

Запуск:
  make autopilot-calendar-apply project_id=1 calendar_plan_id=3
  python -m app.scripts.autopilot_calendar_apply --project-id 1 --calendar-plan-id 3

Создаёт/обновляет план публикаций автопилота из календаря. НЕ публикует, live-флаги не трогает,
внешних вызовов нет — реальная публикация проходит существующие условия безопасности.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.autopilot_calendar_assistant_service import (
    get_autopilot_calendar_assistant_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов применения календаря."""
    parser = argparse.ArgumentParser(description="Применить календарь автопостинга к автопилоту")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--calendar-plan-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI применения календаря."""
    args = build_parser().parse_args()
    service = get_autopilot_calendar_assistant_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.apply_calendar_to_project(db, args.project_id, args.calendar_plan_id)
    print(f"calendar_plan_id:   {result['calendar_plan_id']}")
    print(f"publishing_plan_id: {result['publishing_plan_id']}")
    print(f"status:             {result['status']}")
    print(f"live_publish:       {result['live_publish']}")
    print(result["note"])


if __name__ == "__main__":
    main()
