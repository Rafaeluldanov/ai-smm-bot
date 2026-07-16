"""CLI feedback loop пилота — v1.0.0.

Запуск:
  make pilot-feedback workspace_id=1 decision=accepted
  python -m app.scripts.pilot_feedback --workspace-id 1 --decision accepted \
      [--recommendation-id 3] [--comment "Беру в работу"] [--result "Выручка +10%"] [--user-id 5]

Сохраняет решение владельца по AI-рекомендации (accepted/rejected/modified). Feedback ТОЛЬКО
фиксируется — НЕ выполняет рекомендацию и бизнес не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_pilot_service import AIBusinessPilotError, PilotModeDisabledError
from app.services.ai_pilot_feedback_service import get_ai_pilot_feedback_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов feedback."""
    parser = argparse.ArgumentParser(description="Feedback loop пилота AI Business OS")
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--decision", required=True, choices=["accepted", "rejected", "modified"])
    parser.add_argument("--recommendation-id", type=int, default=None)
    parser.add_argument("--comment", default=None)
    parser.add_argument("--result", default=None)
    parser.add_argument("--user-id", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI feedback."""
    args = build_parser().parse_args()
    service = get_ai_pilot_feedback_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            feedback = service.submit_feedback(
                db,
                args.workspace_id,
                decision=args.decision,
                recommendation_id=args.recommendation_id,
                comment=args.comment,
                result=args.result,
                user_id=args.user_id,
            )
        except (AIBusinessPilotError, PilotModeDisabledError) as exc:
            print(f"Ошибка: {exc}")
            return
    print(
        f"feedback #{feedback['id']}: решение={feedback['decision']} "
        f"(workspace #{feedback['workspace_id']})"
    )
    if feedback.get("comment"):
        print(f"комментарий: {feedback['comment']}")
    if feedback.get("result"):
        print(f"результат: {feedback['result']}")
    print("Сохранено. Feedback НЕ выполняет рекомендацию и бизнес не меняет.")


if __name__ == "__main__":
    main()
