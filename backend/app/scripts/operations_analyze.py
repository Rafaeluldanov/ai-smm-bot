"""CLI операционного анализа AI Operations Control Center — v0.7.3.

Запуск:
  make operations-analyze project_id=1
  python -m app.scripts.operations_analyze --project-id 1

Собирает снапшот: сигналы → health → риски → рекомендации. Advisory: ничего не выполняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_operations_control_service import (
    AIOperationsControlError,
    get_ai_operations_control_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов операционного анализа."""
    parser = argparse.ArgumentParser(description="Операционный анализ AI Operations Control Center")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI операционного анализа."""
    args = build_parser().parse_args()
    service = get_ai_operations_control_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.build_operations_snapshot(db, args.project_id)
        except AIOperationsControlError as exc:
            print(f"Ошибка: {exc}")
            return
    snap = out["snapshot"]
    print(f"health_score:   {snap['health_score']} / 100 ({snap['status']})")
    print(f"metrics:        {snap['metrics']}")
    print(f"risks:          {len(out['risks'])}")
    for r in out["risks"]:
        print(f"  ⚠ [{r['severity']}] {r['title']} ({r['risk_type']})")
    print(f"recommendations: {len(out['recommendations'])} создано")
    for rec in out["recommendations"]:
        print(f"  [{rec['priority']}] {rec['title']}")


if __name__ == "__main__":
    main()
