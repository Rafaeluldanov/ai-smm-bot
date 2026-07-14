"""CLI рекомендаций AI Learning Loop — v0.6.5.

Запуск:
  make ai-learning-recommend project_id=1
  python -m app.scripts.ai_learning_recommend --project-id 1

Показывает рекомендации следующего контента + стратегию. Рекомендации НЕ применяются.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_learning_service import AILearningError, get_ai_learning_service
from app.services.content_strategy_service import get_content_strategy_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов рекомендаций обучения."""
    parser = argparse.ArgumentParser(description="Рекомендации AI Learning Loop")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI рекомендаций обучения."""
    args = build_parser().parse_args()
    service = get_ai_learning_service()
    strategy = get_content_strategy_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            rec = service.recommend_next_content(db, args.project_id)
            strat = strategy.recommend_strategy(db, args.project_id)
        except AILearningError as exc:
            print(f"Ошибка: {exc}")
            return
    print("== Следующий контент ==")
    print(f"topics:      {', '.join(str(t) for t in rec['recommended_topics']) or '—'}")
    print(f"formats:     {', '.join(str(f) for f in rec['recommended_formats']) or '—'}")
    print(f"style:       {rec['recommended_style'] or '—'}")
    print(f"best_time:   {rec['best_time'] or '—'}")
    print(f"confidence:  {rec['confidence']} / 100")
    print("== Стратегия (рекомендация, не применяется) ==")
    print(f"frequency:   {strat['posting_frequency']}")
    print(f"tone:        {strat['tone'] or '—'}")
    print(f"media_style: {strat['media_style'] or '—'}")
    print(f"cta:         {', '.join(str(c) for c in strat['cta']) or '—'}")


if __name__ == "__main__":
    main()
