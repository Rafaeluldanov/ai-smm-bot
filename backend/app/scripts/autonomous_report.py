"""CLI отчёта по автономному прогону (без сети и AI).

Запуск:
  make autonomous-report run_id=1
  python -m app.scripts.autonomous_report --run-id 1
"""

import argparse

from app.api.deps import get_autonomous_pipeline_service
from app.db.session import get_sessionmaker
from app.services.autonomous_pipeline_service import AutonomousRunNotFoundError


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта."""
    parser = argparse.ArgumentParser(description="Отчёт по автономному прогону")
    parser.add_argument("--run-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по прогону."""
    args = build_parser().parse_args()
    service = get_autonomous_pipeline_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            report = service.build_report(db, args.run_id)
        except AutonomousRunNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return

    print(f"Прогон id={report.run_id} | проект={report.project_slug} | режим={report.mode}")
    print(f"Статус: {report.status}")
    summary = report.summary
    print(
        f"Темы={summary.selected_topics_count} посты={summary.generated_posts_count} "
        f"needs_media={summary.posts_needing_media_count} "
        f"внешние={summary.external_candidates_count} "
        f"на ревью={summary.submitted_for_review_count} "
        f"запланировано={summary.scheduled_publications_count} "
        f"опубликовано={summary.published_publications_count}"
    )
    print("\nЧто делать дальше:")
    for action in report.next_actions:
        print(f"  → {action}")
    if report.warnings:
        print("\nПредупреждения:")
        for warning in report.warnings:
            print(f"  ! {warning}")


if __name__ == "__main__":
    main()
