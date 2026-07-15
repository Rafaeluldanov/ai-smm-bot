"""CLI применения AI-кампании — v0.6.7.

Запуск:
  make campaign-apply campaign_id=1
  python -m app.scripts.ai_campaign_apply --campaign-id 1

Одобряет (approve) и применяет кампанию с подтверждением APPLY_CAMPAIGN.
Создаёт только ЧЕРНОВИК календаря — НЕ публикует и НЕ включает live.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_campaign_manager_service import (
    APPLY_CONFIRMATION,
    AICampaignError,
    get_ai_campaign_manager_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов применения кампании."""
    parser = argparse.ArgumentParser(description="Применение AI-кампании")
    parser.add_argument("--campaign-id", type=int, required=True)
    parser.add_argument(
        "--no-approve", action="store_true", help="не одобрять автоматически перед apply"
    )
    return parser


def main() -> None:
    """Точка входа CLI применения кампании."""
    args = build_parser().parse_args()
    service = get_ai_campaign_manager_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if not args.no_approve:
                service.approve_campaign(db, args.campaign_id)
            result = service.apply_campaign(db, args.campaign_id, confirmation=APPLY_CONFIRMATION)
        except AICampaignError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"calendar_draft_created: {result['calendar_draft_created']}")
    print(f"live_enabled:           {result['live_enabled']}")
    print(f"note:                   {result['note']}")


if __name__ == "__main__":
    main()
