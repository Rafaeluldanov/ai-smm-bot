"""CLI исполнительного анализа Autonomous Business OS — v0.7.0.

Запуск:
  make business-os-analyze project_id=1
  python -m app.scripts.business_os_analyze --project-id 1

Собирает состояние бизнеса из всех слоёв (без построения плана). Advisory: ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_executive_service import AIExecutiveError, get_ai_executive_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов исполнительного анализа."""
    parser = argparse.ArgumentParser(description="Исполнительный анализ Autonomous Business OS")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI исполнительного анализа."""
    args = build_parser().parse_args()
    service = get_ai_executive_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            state = service.analyze_business_state(db, args.project_id)
        except AIExecutiveError as exc:
            print(f"Ошибка: {exc}")
            return
    rev = state["revenue_state"]
    print(f"project_id:      {state['project_id']}")
    print(f"business_health: {state['business_health']} / 100")
    print(f"growth_score:    {state['growth_score']} / 100")
    print(f"revenue:         {rev['total_revenue']} (конверсия {rev['conversion_rate']})")
    opps = state.get("opportunities") or []
    print(f"opportunities:   {len(opps)}")
    for o in opps:
        title = o.get("title") if isinstance(o, dict) else str(o)
        print(f"  • {title}")
    risks = state.get("risks") or []
    print(f"risks:           {', '.join(str(r) for r in risks) or '—'}")


if __name__ == "__main__":
    main()
