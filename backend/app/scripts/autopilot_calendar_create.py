"""CLI создания календаря автопостинга — v0.5.8.

Запуск:
  make autopilot-calendar-create project_id=1 preset=three_per_week goal=mixed dry_run=true
  python -m app.scripts.autopilot_calendar_create --project-id 1 --preset ... --dry-run true

По умолчанию dry-run (без записи). Создаёт AutopilotCalendarPlan как черновик; НЕ применяет к
автопилоту, НЕ публикует, live-флаги не трогает, внешних вызовов нет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.autopilot_calendar_assistant_service import (
    get_autopilot_calendar_assistant_service,
)


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания календаря."""
    parser = argparse.ArgumentParser(description="Создать календарь автопостинга")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--preset", type=str, default=None)
    parser.add_argument("--goal", type=str, default=None)
    parser.add_argument("--time", type=str, default=None, help="Время публикации HH:MM")
    parser.add_argument("--platforms", type=str, default=None, help="Через запятую")
    parser.add_argument("--dry-run", dest="dry_run", type=str, default="true")
    return parser


def main() -> None:
    """Точка входа CLI создания календаря."""
    args = build_parser().parse_args()
    payload: dict[str, object] = {}
    if args.preset:
        payload["preset"] = args.preset
    if args.goal:
        payload["goal"] = args.goal
    if args.time:
        payload["publish_times"] = [args.time]
    if args.platforms:
        payload["platforms"] = [p.strip() for p in args.platforms.split(",") if p.strip()]
    dry_run = _as_bool(args.dry_run)
    service = get_autopilot_calendar_assistant_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.create_calendar_plan(db, args.project_id, payload, dry_run=dry_run)
    print(f"dry_run:         {dry_run}")
    if dry_run:
        est = result["estimates"]
        print(f"preset:          {result['preset']}")
        print(f"posts_per_month: {est['estimated_posts_per_month']}")
        print(f"writes:          {result['writes']}")
        print("Ничего не записано (dry-run). Уберите --dry-run false, чтобы создать календарь.")
    else:
        print(f"calendar_plan_id: {result['id']}")
        print(f"status:           {result['status']}")
        print(f"preset:           {result['preset']}")
        print("Календарь создан (черновик). Примените его: autopilot-calendar-apply.")


if __name__ == "__main__":
    main()
