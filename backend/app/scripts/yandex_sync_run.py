"""CLI запуска авто-синхронизации Яндекс Диска (DRY-RUN по умолчанию) — v0.5.7.

Запуск:
  make yandex-sync-run project_id=1 dry_run=true
  python -m app.scripts.yandex_sync_run --project-id 1 --dry-run true

Реальная запись — только при YANDEX_AUTO_SYNC_NETWORK_ENABLED=true и --dry-run false. Файлы не
удаляются. public_url — маской; секретов/путей нет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.yandex_auto_sync_service import get_yandex_auto_sync_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов запуска синхронизации."""
    parser = argparse.ArgumentParser(description="Запуск авто-синхронизации Яндекс Диска (dry-run)")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--dry-run", default="true", help="Dry-run по умолчанию (без записи медиа)")
    return parser


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> None:
    """Точка входа CLI запуска синхронизации."""
    args = build_parser().parse_args()
    dry_run = _truthy(args.dry_run)
    service = get_yandex_auto_sync_service()
    factory = get_sessionmaker()
    with factory() as db:
        run = service.run_sync(db, args.project_id, dry_run=dry_run)
    print(f"status:         {run['status']}")
    print(f"dry_run:        {run['dry_run']}")
    print(f"files_seen:     {run['files_seen']}")
    print(f"files_imported: {run['files_imported']}")
    print(f"files_failed:   {run['files_failed']}")
    if run.get("blockers"):
        for b in run["blockers"]:
            print(f"  — {b.get('message', b.get('type'))}")
    print("Файлы не удаляются; реальная синхронизация — только при явных флагах.")


if __name__ == "__main__":
    main()
