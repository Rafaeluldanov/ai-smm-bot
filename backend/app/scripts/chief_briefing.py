"""CLI брифинга AI Chief of Staff — v0.7.1.

Запуск:
  make chief-briefing project_id=1            # ежедневный брифинг
  make chief-briefing project_id=1 weekly=1   # обзор недели
  python -m app.scripts.chief_briefing --project-id 1 [--weekly]

Собирает executive briefing + задачи владельца. Advisory: ничего не выполняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_chief_of_staff_service import (
    AIChiefOfStaffError,
    get_ai_chief_of_staff_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов брифинга."""
    parser = argparse.ArgumentParser(description="Брифинг AI Chief of Staff")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--weekly", action="store_true", help="еженедельный обзор")
    return parser


def main() -> None:
    """Точка входа CLI брифинга."""
    args = build_parser().parse_args()
    service = get_ai_chief_of_staff_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if args.weekly:
                out = service.generate_weekly_review(db, args.project_id)
            else:
                out = service.generate_daily_briefing(db, args.project_id)
        except AIChiefOfStaffError as exc:
            print(f"Ошибка: {exc}")
            return
    b = out["briefing"]
    print(f"briefing_id:    {b['id']} ({b['type']})")
    print(f"summary:        {b['summary']}")
    print(f"confidence:     {b['confidence_score']} / 100")
    print(f"key_changes:    {', '.join(str(x) for x in b['key_changes']) or '—'}")
    print(f"risks:          {', '.join(str(x) for x in b['risks']) or '—'}")
    print(f"opportunities:  {', '.join(str(x) for x in b['opportunities']) or '—'}")
    print(f"tasks:          {len(out['tasks'])} создано")
    for t in out["tasks"]:
        print(f"  [{t['priority']}] {t['title']} (score {t['priority_score']})")


if __name__ == "__main__":
    main()
