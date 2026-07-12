"""CLI предпросмотра решения автовыбора медиа (без записи, без списаний).

Запуск:
  make media-decision-preview project_id=1 platform=telegram plan_id=1
  python -m app.scripts.media_decision_preview --project-id 1 --platform telegram --plan-id 1

Live-публикаций нет; публичные ссылки не создаются; секреты/пути к файлам не печатаются.
"""

import argparse

from app.api.deps import get_media_decision_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра решения о медиа."""
    parser = argparse.ArgumentParser(description="Предпросмотр решения автовыбора медиа")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--plan-id", type=int, default=None)
    parser.add_argument("--topic-decision-id", type=int, default=None)
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI предпросмотра решения о медиа."""
    args = build_parser().parse_args()
    service = get_media_decision_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.preview_media_decision_for_plan(
            db,
            args.project_id,
            _platform(args.platform),
            plan_id=args.plan_id,
            topic_decision_id=args.topic_decision_id,
        )
    print(f"Предпросмотр медиа-решения: проект {result['project_id']} (без записи)")
    print(f"  стратегия: {result['selected_strategy']} · источник: {result['decision_source']}")
    print(f"  медиа: {result['selected_media_count']} шт · теги: {result['selected_media_tags']}")
    print(
        f"  public image_url: {result['needs_public_image_url']} · "
        f"media proxy готов: {result['media_proxy_ready']}"
    )
    print(f"  уверенность: {result['confidence_score']} · риски: {result['risk_flags']}")
    print(f"  причины: {result['reasons'][:3]}")
    print("  Live-публикаций нет; публичные ссылки не создаются.")


if __name__ == "__main__":
    main()
