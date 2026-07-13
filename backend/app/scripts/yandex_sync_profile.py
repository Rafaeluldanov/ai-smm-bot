"""CLI профиля авто-синхронизации Яндекс Диска (read-only сводка) — v0.5.7.

Запуск:
  make yandex-sync-profile project_id=1
  python -m app.scripts.yandex_sync_profile --project-id 1

Печатает статус/медиатеку/последнюю проверку. public_url — только маской; секретов/путей нет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.yandex_auto_sync_service import get_yandex_auto_sync_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов профиля синхронизации."""
    parser = argparse.ArgumentParser(description="Профиль авто-синхронизации Яндекс Диска")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI профиля синхронизации."""
    args = build_parser().parse_args()
    service = get_yandex_auto_sync_service()
    factory = get_sessionmaker()
    with factory() as db:
        dashboard = service.build_dashboard(db, args.project_id)
    profile = dashboard["profile"]
    summary = dashboard["simple_client_summary"]
    print(f"status:        {dashboard['status']}")
    print(f"public_url:    {profile.get('public_url_masked') or '—'}")
    print(f"root_folder:   {profile.get('root_folder') or '—'}")
    print(
        f"media_count:   {dashboard['media_count']} "
        f"(картинки {dashboard['image_count']}, видео {dashboard['video_count']})"
    )
    print(f"last_sync:     {(dashboard['last_sync'] or {}).get('at') or 'проверок не было'}")
    print(f"client:        {summary['headline']} · {summary['detail']}")
    print("Файлы не удаляются; реальной сети нет по умолчанию.")


if __name__ == "__main__":
    main()
