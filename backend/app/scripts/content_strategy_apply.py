"""CLI применения рекомендации контент-стратегии — v0.6.6.

Запуск:
  make strategy-apply project_id=1 rec_id=5
  python -m app.scripts.content_strategy_apply --project-id 1 --recommendation-id 5

Одобряет (если нужно) и применяет рекомендацию с подтверждением APPLY_STRATEGY.
Меняет только правила/черновик календаря — НЕ публикует и НЕ включает live.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.content_strategist_service import (
    APPLY_CONFIRMATION,
    ContentStrategistError,
    get_content_strategist_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов применения рекомендации."""
    parser = argparse.ArgumentParser(description="Применение рекомендации стратегии")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--recommendation-id", type=int, required=True)
    parser.add_argument("--accept", action="store_true", help="сначала одобрить (accept)")
    return parser


def main() -> None:
    """Точка входа CLI применения рекомендации."""
    args = build_parser().parse_args()
    service = get_content_strategist_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if args.accept:
                service.accept_recommendation(db, args.project_id, args.recommendation_id)
            result = service.apply_recommendation(
                db,
                args.project_id,
                args.recommendation_id,
                confirmation=APPLY_CONFIRMATION,
            )
        except ContentStrategistError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"applied:        {result['applied']}")
    print(f"live_enabled:   {result['live_enabled']}")
    print(f"note:           {result['note']}")


if __name__ == "__main__":
    main()
