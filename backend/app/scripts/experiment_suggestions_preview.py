"""CLI preview предложений экспериментов (без записи и без списания units).

Запуск:
  make experiment-suggestions-preview project_id=1 platform=telegram limit=10
  python -m app.scripts.experiment_suggestions_preview --project-id 1 --platform telegram --limit 10
"""

import argparse

from app.api.deps import get_experiment_suggestion_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов preview предложений."""
    parser = argparse.ArgumentParser(description="Preview предложений экспериментов (без записи)")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--limit", type=int, default=None)
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI preview предложений."""
    args = build_parser().parse_args()
    service = get_experiment_suggestion_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.preview_suggestions(
            db, args.project_id, _platform(args.platform), args.limit
        )
    print(
        f"Preview предложений: проект {result['project_id']}, "
        f"порог уверенности {result['min_confidence']}"
    )
    if not result["suggestions"]:
        print("  Пока недостаточно данных — соберите feedback и метрики.")
    for s in result["suggestions"]:
        mark = "" if s.get("meets_confidence") else " (ниже порога)"
        conf = round(float(s.get("confidence_score", 0) or 0) * 100)
        print(f"  [{s['suggestion_type']}] {s['topic']} — {conf}%{mark}")


if __name__ == "__main__":
    main()
