"""CLI рекомендаций тем (без записи и без списания units).

Запуск:
  make topic-recommendations project_id=1 platform=telegram limit=10
  python -m app.scripts.topic_recommendations --project-id 1 --platform telegram --limit 10
"""

import argparse

from app.api.deps import get_topic_optimization_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов рекомендаций тем."""
    parser = argparse.ArgumentParser(description="Рекомендации тем (без записи)")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--limit", type=int, default=10)
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI рекомендаций тем."""
    args = build_parser().parse_args()
    service = get_topic_optimization_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.recommend_next_topics(
            db, args.project_id, _platform(args.platform), args.limit
        )
    print(
        f"Рекомендации тем: проект {result['project_id']}, "
        f"уверенность {round(result['confidence_score'] * 100)}%"
    )
    if not result["recommendations"]:
        print("  Пока недостаточно данных — соберите feedback и метрики.")
    for rec in result["recommendations"]:
        print(
            f"  [{rec['category']}] {rec['topic']} — {round(rec['confidence_score'] * 100)}% "
            f"({rec['reason']})"
        )


if __name__ == "__main__":
    main()
