"""CLI регистрации события лида/выручки — v0.6.8.

Запуск:
  make sales-lead project_id=1 event=deal_won value=50000 [post_id=12]
  python -m app.scripts.sales_intelligence_lead --project-id 1 --event deal_won --value 50000

Записывает сигнал лида/выручки для атрибуции. Ничего не отправляет и не меняет CRM.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_sales_intelligence_service import (
    AISalesIntelligenceError,
    get_ai_sales_intelligence_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов регистрации лида."""
    parser = argparse.ArgumentParser(description="Регистрация события лида/выручки")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument(
        "--event", type=str, required=True, help="lead_created|deal_created|deal_won|revenue_added"
    )
    parser.add_argument("--source", type=str, default="manual")
    parser.add_argument("--value", type=float, default=0.0)
    parser.add_argument("--post-id", type=int, default=None)
    parser.add_argument("--campaign-id", type=int, default=None)
    parser.add_argument("--platform", type=str, default=None)
    return parser


def main() -> None:
    """Точка входа CLI регистрации лида."""
    args = build_parser().parse_args()
    service = get_ai_sales_intelligence_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            row = service.record_lead_event(
                db,
                args.project_id,
                event_type=args.event,
                source_type=args.source,
                post_id=args.post_id,
                campaign_id=args.campaign_id,
                platform_key=args.platform,
                value=args.value,
            )
        except AISalesIntelligenceError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"lead_event_id:  {row['id']}")
    print(f"event_type:     {row['event_type']}")
    print(f"value:          {row['value']}")
    print(f"post_id:        {row['post_id']} · campaign_id: {row['campaign_id']}")


if __name__ == "__main__":
    main()
