"""CLI согласования поста (без сети, Telegram и AI).

Запуск:
  make review-post post_id=1 action=submit
  python -m app.scripts.review_post --post-id 1 --action approve --actor-name "Stanislav"
"""

import argparse

from sqlalchemy.orm import Session

from app.api.deps import get_post_review_service
from app.db.session import get_sessionmaker
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post_review import PostReviewCommentRequest, PostReviewDecisionRequest
from app.services.post_review_service import PostReviewService, ReviewActionNotAllowedError
from app.services.post_status_service import (
    InvalidPostStatusError,
    InvalidPostStatusTransitionError,
)

# Действия, доступные из CLI.
REVIEW_ACTIONS: list[str] = [
    "submit",
    "approve",
    "reject",
    "request_changes",
    "return_to_draft",
    "comment",
]


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов CLI согласования."""
    parser = argparse.ArgumentParser(description="Согласование черновика поста")
    parser.add_argument("--post-id", type=int, required=True)
    parser.add_argument("--action", required=True, choices=REVIEW_ACTIONS)
    parser.add_argument("--comment", default=None)
    parser.add_argument("--actor-name", default=None)
    parser.add_argument("--actor-role", default="manager")
    return parser


def parse_review_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы CLI (вынесено для тестируемости)."""
    return build_parser().parse_args(argv)


def _dispatch(service: PostReviewService, db: Session, args: argparse.Namespace) -> tuple[str, int]:
    """Выполнить действие и вернуть (описание_статуса, число_действий)."""
    if args.action == "comment":
        action = service.add_comment(
            db,
            args.post_id,
            PostReviewCommentRequest(
                comment=args.comment or "",
                actor_name=args.actor_name,
                actor_role=args.actor_role,
            ),
        )
        return f"комментарий ({action.action})", action.id

    request = PostReviewDecisionRequest(
        comment=args.comment, actor_name=args.actor_name, actor_role=args.actor_role
    )
    methods = {
        "submit": service.submit_for_review,
        "approve": service.approve_post,
        "reject": service.reject_post,
        "request_changes": service.request_changes,
        "return_to_draft": service.return_to_draft,
    }
    card = methods[args.action](db, args.post_id, request)
    return card.status, card.review_actions_count


def main() -> None:
    """Точка входа CLI согласования."""
    args = parse_review_args()
    service = get_post_review_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result, count = _dispatch(service, db, args)
        except (
            PostNotFoundError,
            InvalidPostStatusError,
            InvalidPostStatusTransitionError,
            ReviewActionNotAllowedError,
        ) as exc:
            print(f"Ошибка: {exc}")
            return

    print(f"Пост {args.post_id}: {args.action} → {result} (действий: {count})")


if __name__ == "__main__":
    main()
