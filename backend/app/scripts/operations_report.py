"""CLI операционного отчёта AI Operations Control Center — v0.7.3.

Запуск:
  make operations-report project_id=1
  python -m app.scripts.operations_report --project-id 1

Только чтение: последний снапшот + риски + рекомендации + объяснение. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_operations_control_service import (
    AIOperationsControlError,
    get_ai_operations_control_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов операционного отчёта."""
    parser = argparse.ArgumentParser(description="Операционный отчёт AI Operations Control Center")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI операционного отчёта."""
    args = build_parser().parse_args()
    service = get_ai_operations_control_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            bundle = service.get_operations(db, args.project_id)
            explanation = service.explain_operations_state(db, args.project_id)
        except AIOperationsControlError as exc:
            print(f"Ошибка: {exc}")
            return
    if not bundle["has_snapshot"]:
        print("Снапшотов нет — запустите operations-analyze.")
        return
    snap = bundle["snapshot"]
    print(f"health_score:   {snap['health_score']} / 100 ({snap['status']})")
    print(f"metrics:        {snap['metrics']}")
    print(f"open risks:     {len(bundle['risks'])}")
    for r in bundle["risks"]:
        print(f"  ⚠ [{r['severity']}] {r['title']}")
    print(f"recommendations: {len(bundle['recommendations'])}")
    for rec in bundle["recommendations"]:
        print(f"  [{rec['priority']}] {rec['title']}")
    print("why:")
    for reason in explanation["reasons"]:
        print(f"  • {reason}")


if __name__ == "__main__":
    main()
