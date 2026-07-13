"""CLI предпросмотра авто-синхронизации Яндекс Диска (без записи) — v0.5.7.

Запуск:
  make yandex-sync-preview project_id=1 limit=50
  python -m app.scripts.yandex_sync_preview --project-id 1 [--limit 50]

Без записи медиа, без сети по умолчанию. public_url — маской; секретов/путей нет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.yandex_auto_sync_service import get_yandex_auto_sync_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра синхронизации."""
    parser = argparse.ArgumentParser(description="Предпросмотр авто-синхронизации Яндекс Диска")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI предпросмотра синхронизации."""
    args = build_parser().parse_args()
    service = get_yandex_auto_sync_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.preview_sync(db, args.project_id, limit=args.limit)
    media = result["current_media"]
    print(f"dry_run:         {result['dry_run']}")
    print(f"network_enabled: {result['network_enabled']}")
    print(f"would_sync:      {result['would_sync']}")
    print(f"public_url:      {result.get('public_url_masked') or '—'}")
    print(
        f"current_media:   {media['total']} (картинки {media['images']}, видео {media['videos']})"
    )
    print(f"writes:          {result['writes']}")
    print(result["note"])


if __name__ == "__main__":
    main()
