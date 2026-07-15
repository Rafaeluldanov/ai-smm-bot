"""CLI отчёта AI Business Growth Agent — v0.6.9.

Запуск:
  make growth-report project_id=1
  python -m app.scripts.growth_report --project-id 1

Показывает состояние роста + рекомендации. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.business_growth_agent_service import (
    BusinessGrowthError,
    get_business_growth_agent_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта роста."""
    parser = argparse.ArgumentParser(description="Отчёт AI Business Growth Agent")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта роста."""
    args = build_parser().parse_args()
    service = get_business_growth_agent_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            g = service.get_growth(db, args.project_id)
            recs = service.list_recommendations(db, args.project_id)
        except BusinessGrowthError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"growth_score:   {g['growth_score']} / 100")
    print(f"status:         {g['status']}")
    print(f"strengths:      {', '.join(str(x) for x in g['strengths']) or '—'}")
    print(f"opportunities:  {', '.join(str(x) for x in g['opportunities']) or '—'}")
    print(f"risks:          {', '.join(str(x) for x in g['risks']) or '—'}")
    print(f"current_state:  {g['current_state']}")
    print("recommendations:")
    for r in recs:
        print(f"  #{r['id']} [{r['status']}] ({r['recommendation_type']}) {r['title']}")


if __name__ == "__main__":
    main()
