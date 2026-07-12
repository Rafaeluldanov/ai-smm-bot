"""CLI предпросмотра решения автовыбора темы (без записи, без списаний).

Запуск:
  make topic-decision-preview project_id=1 platform=telegram plan_id=1
  python -m app.scripts.topic_decision_preview --project-id 1 --platform telegram --plan-id 1

Live-публикаций нет; секреты не печатаются.
"""

import argparse

from app.api.deps import get_topic_decision_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра решения."""
    parser = argparse.ArgumentParser(description="Предпросмотр решения автовыбора темы")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--plan-id", type=int, default=None)
    parser.add_argument("--category-id", type=int, default=None)
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI предпросмотра решения."""
    args = build_parser().parse_args()
    service = get_topic_decision_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.preview_decision_for_plan(
            db,
            args.project_id,
            _platform(args.platform),
            plan_id=args.plan_id,
            category_id=args.category_id,
        )
    print(f"Предпросмотр решения: проект {result['project_id']} (без записи)")
    print(f"  тема: {result['selected_topic']} · источник: {result['decision_source']}")
    print(f"  CTA: {result['selected_cta']} · формат: {result['selected_format']}")
    print(f"  уверенность: {result['confidence_score']} · риски: {result['risk_flags']}")
    print(f"  причины: {result['reasons'][:3]}")
    print("  Live-публикаций нет.")


if __name__ == "__main__":
    main()
