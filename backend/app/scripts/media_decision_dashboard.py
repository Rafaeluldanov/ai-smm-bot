"""CLI сводки решений автовыбора медиа (read-only, без записи).

Запуск:
  make media-decision-dashboard project_id=1
  python -m app.scripts.media_decision_dashboard --project-id 1

Секреты/пути к файлам не печатаются; live-публикаций нет.
"""

import argparse

from app.api.deps import get_media_decision_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов сводки решений о медиа."""
    parser = argparse.ArgumentParser(description="Сводка решений автовыбора медиа")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI сводки решений о медиа."""
    args = build_parser().parse_args()
    service = get_media_decision_service()
    factory = get_sessionmaker()
    with factory() as db:
        dash = service.build_media_decision_dashboard(db, args.project_id, _platform(args.platform))
    print(f"Сводка медиа-решений: проект {dash['project_id']}")
    print(
        f"  всего: {dash['total']} · низкая уверенность: {dash['low_confidence_count']} · "
        f"без медиа: {dash['no_media_count']}"
    )
    print(f"  средняя уверенность: {dash['avg_confidence']}")
    print(f"  стратегии: {dash['top_strategies']}")
    print(f"  теги: {dash['top_media_tags']}")
    print(f"  риски: {dash['risk_flags']}")
    print(f"  worker включён: {dash['worker_enabled']} · live-публикаций нет")


if __name__ == "__main__":
    main()
