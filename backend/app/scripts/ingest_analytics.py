"""CLI ручного ввода метрик аналитики (без сети и AI).

Запуск:
  make ingest-analytics post_id=1
  python -m app.scripts.ingest_analytics --post-id 1 --platform telegram \
      --impressions 1000 --reach 800 --likes 30 --comments 5 --shares 2 --clicks 20
"""

import argparse

from app.api.deps import get_analytics_provider, get_analytics_service
from app.db.session import get_sessionmaker
from app.repositories.post_repository import PostNotFoundError
from app.schemas.analytics import PostAnalyticsSnapshotCreate


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов ручного ввода метрик."""
    parser = argparse.ArgumentParser(description="Ручной ввод метрик аналитики поста")
    parser.add_argument("--post-id", type=int, required=True)
    parser.add_argument("--platform", default="manual")
    parser.add_argument("--source", default="manual")
    for metric in (
        "impressions",
        "reach",
        "views",
        "likes",
        "reactions",
        "comments",
        "shares",
        "saves",
        "clicks",
    ):
        parser.add_argument(f"--{metric}", type=int, default=0)
    return parser


def main() -> None:
    """Точка входа CLI ввода метрик."""
    args = build_parser().parse_args()
    request = PostAnalyticsSnapshotCreate(
        post_id=args.post_id,
        platform=args.platform,
        source=args.source,
        impressions=args.impressions,
        reach=args.reach,
        views=args.views,
        likes=args.likes,
        reactions=args.reactions,
        comments=args.comments,
        shares=args.shares,
        saves=args.saves,
        clicks=args.clicks,
    )

    service = get_analytics_service(get_analytics_provider())
    factory = get_sessionmaker()
    with factory() as db:
        try:
            snapshot = service.ingest_snapshot(db, request)
        except PostNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return

    print(
        f"Снимок id={snapshot.id}: post={snapshot.post_id} platform={snapshot.platform} "
        f"CTR={snapshot.ctr} ER={snapshot.engagement_rate}"
    )


if __name__ == "__main__":
    main()
