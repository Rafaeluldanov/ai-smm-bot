"""CLI профиля AI Learning Loop — v0.6.5.

Запуск:
  make ai-learning-profile project_id=1
  python -m app.scripts.ai_learning_profile --project-id 1

Показывает сводку профиля обучения проекта. Секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_learning_service import AILearningError, get_ai_learning_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов профиля обучения."""
    parser = argparse.ArgumentParser(description="Профиль AI Learning Loop")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI профиля обучения."""
    args = build_parser().parse_args()
    service = get_ai_learning_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            s = service.get_summary(db, args.project_id)
        except AILearningError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"project_id:        {s['project_id']}")
    print(f"status:            {s['status']}")
    print(f"learning_score:    {s['learning_score']} / 100")
    print(f"posts_analyzed:    {s['total_posts_analyzed']}")
    print(f"feedback_events:   {s['total_feedback_events']}")
    print(f"preferred_topics:  {', '.join(str(t) for t in s['preferred_topics']) or '—'}")
    print(f"preferred_formats: {', '.join(str(f) for f in s['preferred_formats']) or '—'}")
    print(f"preferred_styles:  {', '.join(str(x) for x in s['preferred_styles']) or '—'}")
    print(f"best_times:        {', '.join(str(t) for t in s['best_publish_times']) or '—'}")
    print(f"best_platforms:    {', '.join(str(p) for p in s['best_platforms']) or '—'}")
    print(f"event_counts:      {s['event_counts']}")


if __name__ == "__main__":
    main()
