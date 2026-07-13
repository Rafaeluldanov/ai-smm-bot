"""CLI предпросмотра календаря автопостинга (без записи) — v0.5.8.

Запуск:
  make autopilot-calendar-preview project_id=1 preset=three_per_week goal=mixed
  python -m app.scripts.autopilot_calendar_preview --project-id 1 [--preset ...] [--goal ...]

Строит календарь и печатает дни/время/оценки/риски. Ничего не пишет, не публикует,
live-флаги не трогает, внешних вызовов нет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.autopilot_calendar_assistant_service import (
    get_autopilot_calendar_assistant_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра календаря."""
    parser = argparse.ArgumentParser(description="Предпросмотр календаря автопостинга")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--preset", type=str, default=None)
    parser.add_argument("--goal", type=str, default=None)
    parser.add_argument("--time", type=str, default=None, help="Время публикации HH:MM")
    parser.add_argument("--platforms", type=str, default=None, help="Через запятую")
    return parser


def main() -> None:
    """Точка входа CLI предпросмотра календаря."""
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
    service = get_autopilot_calendar_assistant_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.preview_calendar(db, args.project_id, payload)
    est = result["estimates"]
    print(f"preset:          {result['preset']}")
    print(f"goal:            {result['goal']}")
    print(f"weekdays:        {', '.join(result['weekday_labels']) or '—'}")
    print(f"publish_times:   {', '.join(result['publish_times'])}")
    print(f"platforms:       {', '.join(result['platforms']) or '—'}")
    print(f"posts_per_month: {est['estimated_posts_per_month']}")
    print(f"media_needed:    {est['estimated_media_needed']}")
    print(f"units_per_month: {est['estimated_units_per_month']}")
    print(f"writes:          {result['writes']}")
    for risk in result["risks"]:
        print(f"  risk [{risk['severity']}] {risk['type']}: {risk['message']}")
    print(result["note"])


if __name__ == "__main__":
    main()
