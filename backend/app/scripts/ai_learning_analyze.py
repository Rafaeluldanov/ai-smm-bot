"""CLI анализа AI Learning Loop — v0.6.5.

Запуск:
  make ai-learning-analyze project_id=1
  python -m app.scripts.ai_learning_analyze --project-id 1 --window-days 90

Прогоняет анализ постов + пересчёт профиля. НЕ публикует, live не включает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_learning_service import AILearningError, get_ai_learning_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа обучения."""
    parser = argparse.ArgumentParser(description="Анализ AI Learning Loop")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--window-days", type=int, default=90)
    return parser


def main() -> None:
    """Точка входа CLI анализа обучения."""
    args = build_parser().parse_args()
    service = get_ai_learning_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            s = service.analyze_project(db, args.project_id, window_days=args.window_days)
        except AILearningError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"project_id:        {s['project_id']}")
    print(f"posts_scanned:     {s.get('posts_scanned', 0)}")
    print(f"posts_with_metrics:{s.get('posts_with_metrics', 0)}")
    print(f"learning_score:    {s['learning_score']} / 100")
    print(f"status:            {s['status']}")
    print(f"preferred_formats: {', '.join(str(f) for f in s['preferred_formats']) or '—'}")
    print(f"preferred_topics:  {', '.join(str(t) for t in s['preferred_topics']) or '—'}")


if __name__ == "__main__":
    main()
