"""CLI планирования AI-кампании — v0.6.7.

Запуск:
  make campaign-plan campaign_id=1
  python -m app.scripts.ai_campaign_plan --campaign-id 1

Собирает стратегию + этапы + рекомендации кампании. НЕ публикует, live не включает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_campaign_manager_service import (
    AICampaignError,
    get_ai_campaign_manager_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов планирования кампании."""
    parser = argparse.ArgumentParser(description="Планирование AI-кампании")
    parser.add_argument("--campaign-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI планирования кампании."""
    args = build_parser().parse_args()
    service = get_ai_campaign_manager_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            plan = service.plan_campaign(db, args.campaign_id)
        except AICampaignError as exc:
            print(f"Ошибка: {exc}")
            return
    strategy = plan["strategy"]
    print(f"theme:         {strategy['campaign_theme']}")
    print(f"frequency:     {strategy['posting_frequency']}")
    print(f"kpi:           {strategy['kpi']}")
    print("stages:")
    for s in plan["stages"]:
        print(
            f"  {s['order_number']}. {s['title']} ({s['stage_type']}) — "
            f"темы: {', '.join(str(t) for t in s['recommended_topics'])}"
        )
    print(f"recommendations: {len(plan['recommendations'])} создано")
    for r in plan["recommendations"]:
        print(f"  [{r['recommendation_type']}] {r['title']} ({r['confidence_score']}/100)")


if __name__ == "__main__":
    main()
