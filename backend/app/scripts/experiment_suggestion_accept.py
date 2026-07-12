"""CLI приёма предложения эксперимента (бесплатно, без live-публикации).

Запуск:
  make experiment-suggestion-accept suggestion_id=1
  python -m app.scripts.experiment_suggestion_accept --suggestion-id 1
"""

import argparse

from app.api.deps import get_experiment_suggestion_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов приёма предложения."""
    parser = argparse.ArgumentParser(description="Принять предложение эксперимента")
    parser.add_argument("--suggestion-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI приёма предложения."""
    args = build_parser().parse_args()
    service = get_experiment_suggestion_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.accept_suggestion(db, args.suggestion_id)
    print(f"Предложение #{result['id']} принято (статус {result['status']}).")
    print(f"  тема: {result['topic']}")


if __name__ == "__main__":
    main()
