"""Тесты репозитория журнала согласования."""

from sqlalchemy.orm import Session

from app.repositories import post_repository
from app.repositories import post_review_repository as repo
from app.repositories.project_repository import create_project
from app.schemas.post import PostCreate
from app.schemas.post_review import PostReviewActionCreate
from app.schemas.project import ProjectCreate


def _post_id(db: Session) -> int:
    project_id = create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id
    return post_repository.create_post(
        db, PostCreate(project_id=project_id, title="Футболки", status="draft")
    ).id


def _action(post_id: int, action: str) -> PostReviewActionCreate:
    return PostReviewActionCreate(post_id=post_id, action=action, from_status="draft")


def test_create_and_list(db_session: Session) -> None:
    post_id = _post_id(db_session)
    repo.create_review_action(db_session, _action(post_id, "submit_for_review"))
    repo.create_review_action(db_session, _action(post_id, "approve"))

    actions = repo.list_review_actions(db_session, post_id)
    assert len(actions) == 2
    # Хронологический порядок: старые → новые.
    assert actions[0].action == "submit_for_review"
    assert actions[1].action == "approve"


def test_count_and_last(db_session: Session) -> None:
    post_id = _post_id(db_session)
    assert repo.count_review_actions(db_session, post_id) == 0
    assert repo.get_last_review_action(db_session, post_id) is None

    repo.create_review_action(db_session, _action(post_id, "comment"))
    repo.create_review_action(db_session, _action(post_id, "reject"))

    assert repo.count_review_actions(db_session, post_id) == 2
    last = repo.get_last_review_action(db_session, post_id)
    assert last is not None
    assert last.action == "reject"
