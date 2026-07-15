"""CLI анализа AI Sales Intelligence — v0.6.8.

Запуск:
  make sales-analyze project_id=1
  python -m app.scripts.sales_intelligence_analyze --project-id 1

Пересчитывает профиль продаж + атрибуцию. Аналитика: ничего не публикует и не шлёт.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_sales_intelligence_service import (
    AISalesIntelligenceError,
    get_ai_sales_intelligence_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа продаж."""
    parser = argparse.ArgumentParser(description="Анализ AI Sales Intelligence")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI анализа продаж."""
    args = build_parser().parse_args()
    service = get_ai_sales_intelligence_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            prof = service.build_sales_profile(db, args.project_id)
        except AISalesIntelligenceError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"project_id:        {prof['project_id']}")
    print(f"status:            {prof['status']}")
    print(f"best_lead_topics:  {', '.join(str(t) for t in prof['best_lead_topics']) or '—'}")
    print(f"best_campaigns:    {', '.join(str(c) for c in prof['best_campaigns']) or '—'}")
    print(f"best_cta:          {', '.join(str(c) for c in prof['best_cta']) or '—'}")
    print(f"best_platforms:    {', '.join(str(p) for p in prof['best_platforms']) or '—'}")
    print(f"total_revenue:     {prof['revenue_insights'].get('total_revenue', 0)}")
    print(f"conversion:        {prof['conversion_patterns']}")


if __name__ == "__main__":
    main()
