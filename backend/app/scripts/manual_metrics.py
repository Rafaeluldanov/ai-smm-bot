"""CLI ручного ввода метрик публикации (source=manual, бесплатно, без сети).

Запуск:
  make manual-metrics publication_id=1 views=1000 likes=50 comments=3 shares=4
  python -m app.scripts.manual_metrics --publication-id 1 --views 1000 --likes 50 \
      --comments 3 --shares 4

Неизвестные метрики не передавайте (они не считаются нулём).
"""

import argparse

from app.api.deps import get_metrics_import_service
from app.db.session import get_sessionmaker

_METRICS = (
    "views",
    "reach",
    "impressions",
    "likes",
    "comments",
    "shares",
    "saves",
    "clicks",
    "followers_delta",
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов ручного ввода метрик."""
    parser = argparse.ArgumentParser(description="Ручной ввод метрик публикации (source=manual)")
    parser.add_argument("--publication-id", type=int, required=True)
    for metric in _METRICS:
        parser.add_argument(f"--{metric.replace('_', '-')}", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI ручного ввода метрик."""
    args = build_parser().parse_args()
    metrics = {
        metric: getattr(args, metric) for metric in _METRICS if getattr(args, metric) is not None
    }
    service = get_metrics_import_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.save_manual_metrics(db, args.publication_id, metrics)
    er = result["er_percent"]
    ctr = result["ctr_percent"]
    print(f"Метрики сохранены (source=manual, бесплатно): публикация {result['publication_id']}")
    print(f"  снимок id: {result['snapshot_id']}")
    print(f"  ER: {er if er is not None else '—'}%   CTR: {ctr if ctr is not None else '—'}%")
    print(f"  списано units: {result['units_charged']}")


if __name__ == "__main__":
    main()
