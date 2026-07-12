"""CLI сводки решений автовыбора темы (read-only, без записи).

Запуск:
  make topic-decision-dashboard project_id=1
  python -m app.scripts.topic_decision_dashboard --project-id 1

Секреты не печатаются; live-публикаций нет.
"""

import argparse

from app.api.deps import get_topic_decision_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов сводки решений."""
    parser = argparse.ArgumentParser(description="Сводка решений автовыбора темы")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI сводки решений."""
    args = build_parser().parse_args()
    service = get_topic_decision_service()
    factory = get_sessionmaker()
    with factory() as db:
        dash = service.build_decision_dashboard(db, args.project_id, _platform(args.platform))
    print(f"Сводка решений: проект {dash['project_id']}")
    print(f"  всего: {dash['total']} · низкая уверенность: {dash['low_confidence_count']}")
    print(f"  средняя уверенность: {dash['avg_confidence']}")
    print(f"  источники: {dash['top_sources']}")
    print(f"  темы: {dash['top_topics']}")
    print(f"  worker включён: {dash['worker_enabled']} · live-публикаций нет")


if __name__ == "__main__":
    main()
