"""CLI анализа AI Business Growth Agent — v0.6.9.

Запуск:
  make growth-analyze project_id=1
  python -m app.scripts.growth_analyze --project-id 1

Собирает Growth Intelligence + генерирует рекомендации. Advisory: ничего не меняет сам.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.business_growth_agent_service import (
    BusinessGrowthError,
    get_business_growth_agent_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа роста."""
    parser = argparse.ArgumentParser(description="Анализ AI Business Growth Agent")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI анализа роста."""
    args = build_parser().parse_args()
    service = get_business_growth_agent_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.analyze_and_recommend(db, args.project_id)
        except BusinessGrowthError as exc:
            print(f"Ошибка: {exc}")
            return
    a = out["analysis"]
    print(f"project_id:     {a['project_id']}")
    print(f"growth_score:   {a['growth_score']} / 100")
    print(f"strengths:      {', '.join(str(x) for x in a['strengths']) or '—'}")
    print(f"weaknesses:     {', '.join(str(x) for x in a['weaknesses']) or '—'}")
    print(f"opportunities:  {', '.join(o['title'] for o in a['opportunities']) or '—'}")
    print(f"risks:          {', '.join(str(x) for x in a['risks']) or '—'}")
    print(f"recommendations: {len(out['recommendations'])} создано")
    for r in out["recommendations"]:
        print(f"  [{r['recommendation_type']}] {r['title']} ({r['confidence_score']}/100)")


if __name__ == "__main__":
    main()
