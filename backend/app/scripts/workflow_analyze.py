"""CLI анализа здоровья процесса AI Workflow Manager — v0.7.2.

Запуск:
  make workflow-analyze workflow_id=5
  python -m app.scripts.workflow_analyze --workflow-id 5

Анализирует просрочки/блокеры/риски и выдаёт рекомендации. Ничего не выполняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_workflow_manager_service import (
    AIWorkflowManagerError,
    get_ai_workflow_manager_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа процесса."""
    parser = argparse.ArgumentParser(description="Анализ здоровья процесса AI Workflow Manager")
    parser.add_argument("--workflow-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI анализа процесса."""
    args = build_parser().parse_args()
    service = get_ai_workflow_manager_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            health = service.analyze_workflow_health(db, args.workflow_id)
        except AIWorkflowManagerError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"workflow_id:    {health['workflow_id']}")
    print(f"health_score:   {health['health_score']} / 100")
    print(f"progress:       {health['progress_percent']}%")
    print(f"overdue_steps:  {health['overdue_steps']}")
    print(f"open_blockers:  {health['open_blockers']}")
    print(f"stuck_steps:    {health['stuck_steps']}")
    print(f"risks:          {', '.join(str(r) for r in health['risks']) or '—'}")
    print("recommendations:")
    for r in health["recommendations"]:
        print(f"  • {r}")


if __name__ == "__main__":
    main()
