"""CLI создания AI-кампании — v0.6.7.

Запуск:
  make campaign-create project_id=1 name="Летняя распродажа" goal=sales [product="Худи"]
  python -m app.scripts.ai_campaign_create --project-id 1 --name "..." --goal sales

Создаёт кампанию (status=draft). Ничего не публикует.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_campaign_manager_service import (
    AICampaignError,
    get_ai_campaign_manager_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания кампании."""
    parser = argparse.ArgumentParser(description="Создание AI-кампании")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--name", type=str, required=True)
    parser.add_argument("--goal", type=str, required=True)
    parser.add_argument("--product", type=str, default=None)
    return parser


def main() -> None:
    """Точка входа CLI создания кампании."""
    args = build_parser().parse_args()
    service = get_ai_campaign_manager_service()
    factory = get_sessionmaker()
    product_context = {"name": args.product} if args.product else None
    with factory() as db:
        try:
            camp = service.create_campaign(
                db,
                args.project_id,
                name=args.name,
                goal=args.goal,
                product_context=product_context,
            )
        except AICampaignError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"campaign_id:   {camp['id']}")
    print(f"name:          {camp['name']}")
    print(f"goal:          {camp['goal']}")
    print(f"status:        {camp['status']}")


if __name__ == "__main__":
    main()
