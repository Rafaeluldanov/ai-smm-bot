"""CLI анализа контент-стратегии — v0.6.6.

Запуск:
  make strategy-analyze project_id=1
  python -m app.scripts.content_strategy_analyze --project-id 1

Собирает снапшот стратегии + генерирует рекомендации. НЕ публикует, live не включает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.content_strategist_service import (
    ContentStrategistError,
    get_content_strategist_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа стратегии."""
    parser = argparse.ArgumentParser(description="Анализ контент-стратегии")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI анализа стратегии."""
    args = build_parser().parse_args()
    service = get_content_strategist_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            snap = service.build_strategy_snapshot(db, args.project_id)
            recs = service.generate_recommendations(db, args.project_id)
        except ContentStrategistError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"project_id:        {snap['project_id']}")
    print(f"business_goal:     {snap['business_goal']}")
    print(f"frequency:         {snap['recommended_frequency']}")
    print(
        f"content_pillars:   {', '.join(p.get('name', '') for p in snap['content_pillars']) or '—'}"
    )
    print(f"best_topics:       {', '.join(str(t) for t in snap['best_topics']) or '—'}")
    print(f"best_formats:      {', '.join(str(f) for f in snap['best_formats']) or '—'}")
    print(f"recommendations:   {len(recs)} создано")
    for r in recs:
        print(f"  [{r['recommendation_type']}] {r['title']} ({r['confidence_score']}/100)")
    for w in snap.get("warnings", []):
        print(f"  ! {w}")


if __name__ == "__main__":
    main()
