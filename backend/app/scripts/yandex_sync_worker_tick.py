"""CLI одного tick воркера авто-синхронизации Яндекс Диска (DRY-RUN) — v0.5.7.

Запуск:
  make yandex-sync-worker-tick dry_run=true
  python -m app.scripts.yandex_sync_worker_tick --dry-run true

Worker выключен по умолчанию (YANDEX_AUTO_SYNC_WORKER_ENABLED=false). Реальной сети/записи/удаления
нет по умолчанию. Секретов/путей не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.yandex_auto_sync_service import get_yandex_auto_sync_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов tick воркера синхронизации."""
    parser = argparse.ArgumentParser(description="Tick воркера авто-синхронизации (dry-run)")
    parser.add_argument("--dry-run", default="true", help="Dry-run по умолчанию (без записи)")
    parser.add_argument("--limit", type=int, default=None)
    return parser


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> None:
    """Точка входа CLI tick воркера синхронизации."""
    args = build_parser().parse_args()
    service = get_yandex_auto_sync_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.run_worker_tick(db, dry_run=_truthy(args.dry_run), limit=args.limit)
    print(f"enabled:          {result['enabled']}")
    print(f"dry_run:          {result['dry_run']}")
    print(f"profiles_scanned: {result['profiles_scanned']}")
    print(f"runs_created:     {result['runs_created']}")
    print(f"media_imported:   {result['media_imported']}")
    if result.get("note"):
        print(result["note"])
    print("Реальной сети/удаления нет по умолчанию.")


if __name__ == "__main__":
    main()
