"""CLI отчётов аналитики (без сети и AI).

Запуск:
  make analytics-report project_slug=teeon
  python -m app.scripts.analytics_report --project-slug teeon --type summary
"""

import argparse

from sqlalchemy.orm import Session

from app.api.deps import get_analytics_provider, get_analytics_service
from app.db.session import get_sessionmaker
from app.repositories import project_repository
from app.services.analytics_service import AnalyticsService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

REPORT_TYPES = ["summary", "topics", "clusters", "feedback"]


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта аналитики."""
    parser = argparse.ArgumentParser(description="Отчёты аналитики проекта")
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--project-slug", default=None)
    parser.add_argument("--type", default="summary", choices=REPORT_TYPES)
    return parser


def _resolve_project_id(db: Session, args: argparse.Namespace) -> int | None:
    if args.project_id is not None:
        return int(args.project_id)
    if args.project_slug:
        project = project_repository.get_project_by_slug(db, args.project_slug)
        return project.id if project is not None else None
    return None


def _print_report(
    service: AnalyticsService, db: Session, project_id: int, report_type: str
) -> None:
    if report_type == "topics":
        for topic_item in service.get_topic_performance(db, project_id).items:
            print(
                f"[{topic_item.performance_score:5.1f}] {topic_item.topic_title} "
                f"(cluster={topic_item.cluster})"
            )
    elif report_type == "clusters":
        for cluster_item in service.get_cluster_performance(db, project_id).items:
            print(
                f"[{cluster_item.performance_score:5.1f}] {cluster_item.cluster} "
                f"(постов {cluster_item.posts_count})"
            )
    elif report_type == "feedback":
        report = service.build_feedback_signals(db, project_id)
        for signal in report.signals:
            print(f"[{signal.signal_type}] {signal.cluster}: {signal.reason}")
        for warning in report.warnings:
            print(f"  ! {warning}")
    else:
        summary = service.get_project_summary(db, project_id)
        print(
            f"Проект {summary.project_slug}: постов {summary.posts_count}, "
            f"опубликовано {summary.published_posts_count}, снимков {summary.snapshots_count}"
        )
        print(
            f"Impressions={summary.total_impressions} Reach={summary.total_reach} "
            f"Engagements={summary.total_engagements} Clicks={summary.total_clicks}"
        )
        print(f"avg CTR={summary.avg_ctr} avg ER={summary.avg_engagement_rate}")
        for topic in summary.top_topics:
            print(f"  тема [{topic.performance_score:5.1f}] {topic.topic_title}")
        for cluster in summary.top_clusters:
            print(f"  кластер [{cluster.performance_score:5.1f}] {cluster.cluster}")


def main() -> None:
    """Точка входа CLI отчётов."""
    args = build_parser().parse_args()
    service = get_analytics_service(get_analytics_provider())
    factory = get_sessionmaker()
    with factory() as db:
        project_id = _resolve_project_id(db, args)
        if project_id is None:
            print("Укажите --project-id или существующий --project-slug.")
            return
        try:
            _print_report(service, db, project_id, args.type)
        except ProjectNotFoundError as exc:
            print(f"Ошибка: {exc}")


if __name__ == "__main__":
    main()
