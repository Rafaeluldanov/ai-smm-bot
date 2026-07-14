"""CLI списка рекомендаций контент-стратегии — v0.6.6.

Запуск:
  make strategy-recommend project_id=1
  python -m app.scripts.content_strategy_recommend --project-id 1 [--status generated]

Показывает рекомендации стратегии. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.content_strategist_service import (
    ContentStrategistError,
    get_content_strategist_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов списка рекомендаций."""
    parser = argparse.ArgumentParser(description="Рекомендации контент-стратегии")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--status", type=str, default=None)
    return parser


def main() -> None:
    """Точка входа CLI списка рекомендаций."""
    args = build_parser().parse_args()
    service = get_content_strategist_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            recs = service.list_recommendations(db, args.project_id, status=args.status)
        except ContentStrategistError as exc:
            print(f"Ошибка: {exc}")
            return
    if not recs:
        print("Рекомендаций нет (запустите strategy-analyze).")
        return
    for r in recs:
        print(f"#{r['id']} [{r['status']}] ({r['recommendation_type']}) {r['title']}")
        print(f"    уверенность: {r['confidence_score']}/100 · приоритет: {r['priority']}")
        if r.get("reasoning"):
            print(f"    причины: {'; '.join(str(x) for x in r['reasoning'])}")


if __name__ == "__main__":
    main()
