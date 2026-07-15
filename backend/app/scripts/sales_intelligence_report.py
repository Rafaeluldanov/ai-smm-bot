"""CLI отчёта AI Sales Intelligence — v0.6.8.

Запуск:
  make sales-report project_id=1
  python -m app.scripts.sales_intelligence_report --project-id 1

Показывает, что приносит деньги: топ-контент/кампании/CTA/площадка. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_sales_intelligence_service import (
    AISalesIntelligenceError,
    get_ai_sales_intelligence_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта продаж."""
    parser = argparse.ArgumentParser(description="Отчёт AI Sales Intelligence")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта продаж."""
    args = build_parser().parse_args()
    service = get_ai_sales_intelligence_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            data = service.get_revenue(db, args.project_id)
        except AISalesIntelligenceError as exc:
            print(f"Ошибка: {exc}")
            return
    analysis = data["analysis"]
    summary = data["summary"]
    print(f"total_revenue:  {analysis['total_revenue']}")
    print(f"leads: {summary['leads']} · deals: {summary['deals']} · won: {summary['won_deals']}")
    print("top_content:")
    for c in analysis["top_content"]:
        print(f"  #{c['post_id']} {c['title'] or ''} — {c['revenue']}")
    print("top_campaigns:")
    for c in analysis["top_campaigns"]:
        score = c["campaign_revenue_score"]
        print(f"  #{c['campaign_id']} {c['name'] or ''} — {c['revenue']} (score {score})")
    print(f"best_cta:       {', '.join(analysis['best_cta']) or '—'}")
    print(f"best_platform:  {analysis['best_platform'] or '—'}")
    print(f"revenue_sources:{analysis['revenue_sources']}")


if __name__ == "__main__":
    main()
