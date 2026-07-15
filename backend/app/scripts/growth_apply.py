"""CLI применения рекомендации роста — v0.6.9.

Запуск:
  make growth-apply project_id=1 rec_id=5
  python -m app.scripts.growth_apply --project-id 1 --recommendation-id 5

Одобряет (если нужно) и применяет рекомендацию с подтверждением APPLY_GROWTH_ACTION.
Меняет только business-профиль/черновик стратегии — НЕ live/CRM/бюджет/публикации.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.business_growth_agent_service import (
    APPLY_CONFIRMATION,
    BusinessGrowthError,
    get_business_growth_agent_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов применения рекомендации роста."""
    parser = argparse.ArgumentParser(description="Применение рекомендации роста")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--recommendation-id", type=int, required=True)
    parser.add_argument("--no-accept", action="store_true", help="не одобрять автоматически")
    return parser


def main() -> None:
    """Точка входа CLI применения рекомендации роста."""
    args = build_parser().parse_args()
    service = get_business_growth_agent_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if not args.no_accept:
                service.accept_recommendation(db, args.project_id, args.recommendation_id)
            result = service.apply_recommendation(
                db, args.project_id, args.recommendation_id, confirmation=APPLY_CONFIRMATION
            )
        except BusinessGrowthError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"applied:        {result['applied']}")
    print(f"live_enabled:   {result['live_enabled']}")
    print(f"note:           {result['note']}")


if __name__ == "__main__":
    main()
