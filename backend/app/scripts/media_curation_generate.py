"""CLI генерации задач курирования медиатеки (по умолчанию dry-run — без записи).

Запуск:
  make media-curation-generate project_id=1 dry_run=true
  python -m app.scripts.media_curation_generate --project-id 1 --dry-run false

Пишет задачи только при --dry-run false. Теги НЕ применяются автоматически; файлы НЕ удаляются.
"""

import argparse

from app.api.deps import get_media_curation_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов генерации задач курирования."""
    parser = argparse.ArgumentParser(
        description="Сгенерировать задачи курирования (dry-run по умолчанию)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI генерации задач курирования."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_media_curation_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.generate_curation_tasks(
            db, args.project_id, _platform(args.platform), dry_run=dry_run
        )
    if dry_run:
        print(f"DRY-RUN курирования: проект {result['project_id']} (без записи)")
        print(f"  задач найдено: {result['tasks_found']}")
    else:
        print(f"Курирование: проект {result['project_id']}")
        print(f"  задач создано: {result['tasks_created']}")
    print("  Теги применяются только после подтверждения; файлы не удаляются; внешнего AI нет.")


if __name__ == "__main__":
    main()
