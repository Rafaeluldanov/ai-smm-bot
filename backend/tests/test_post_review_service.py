"""Тесты сервиса согласования постов."""

import pytest
from sqlalchemy.orm import Session

from app.models.post import Post
from app.repositories import media_asset_repository as media_repo
from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.post import PostCreate
from app.schemas.post_review import (
    PostReviewCommentRequest,
    PostReviewDecisionRequest,
    PostReviewEditRequest,
)
from app.schemas.project import ProjectCreate
from app.services.post_review_service import PostReviewService, ReviewActionNotAllowedError
from app.services.post_status_service import InvalidPostStatusTransitionError


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _media(db: Session, project_id: int) -> int:
    return media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="f.jpg",
            yandex_disk_path="disk:/f.jpg",
            status="approved",
            tags={"products": ["футболка"]},
        ),
    ).id


def _post(db: Session, project_id: int, status: str = "draft", media: bool = True) -> Post:
    media_id = _media(db, project_id) if media else None
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            media_asset_id=media_id,
            title="Футболки",
            telegram_text="t",
            vk_text="v",
            instagram_text="i",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status=status,
        ),
    )


_DECISION = PostReviewDecisionRequest(actor_name="Stanislav")


def test_build_card(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id)
    card = PostReviewService().build_review_card(db_session, post.id)
    assert card.post_id == post.id
    assert card.status == "draft"
    assert card.review_actions_count == 0


def test_submit_draft_to_needs_review(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="draft")
    card = PostReviewService().submit_for_review(db_session, post.id, _DECISION)
    assert card.status == "needs_review"
    assert card.review_actions_count == 1


def test_approve_needs_review_to_approved(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="needs_review")
    card = PostReviewService().approve_post(db_session, post.id, _DECISION)
    assert card.status == "approved"


def test_reject_draft(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="draft")
    card = PostReviewService().reject_post(db_session, post.id, _DECISION)
    assert card.status == "rejected"


def test_request_changes_needs_review_to_draft(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="needs_review")
    card = PostReviewService().request_changes(db_session, post.id, _DECISION)
    assert card.status == "draft"


def test_return_to_draft_from_rejected(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="rejected")
    card = PostReviewService().return_to_draft(db_session, post.id, _DECISION)
    assert card.status == "draft"


def test_edit_changes_texts(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="draft")
    request = PostReviewEditRequest(
        telegram_text="НОВЫЙ TG", vk_text="НОВЫЙ VK", instagram_text="НОВЫЙ IG"
    )
    card = PostReviewService().edit_post_texts(db_session, post.id, request)
    assert card.telegram_text == "НОВЫЙ TG"
    assert card.vk_text == "НОВЫЙ VK"
    assert card.instagram_text == "НОВЫЙ IG"


def test_edit_rejected_moves_to_draft(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="rejected")
    card = PostReviewService().edit_post_texts(
        db_session, post.id, PostReviewEditRequest(telegram_text="X")
    )
    assert card.status == "draft"


def test_add_comment_keeps_status(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="draft")
    action = PostReviewService().add_comment(
        db_session, post.id, PostReviewCommentRequest(comment="Поправьте заголовок")
    )
    assert action.action == "comment"
    assert post_repository.get_post_by_id(db_session, post.id).status == "draft"  # type: ignore[union-attr]


def test_needs_media_cannot_submit(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="needs_media", media=False)
    with pytest.raises(ReviewActionNotAllowedError):
        PostReviewService().submit_for_review(db_session, post.id, _DECISION)


def test_published_cannot_edit(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="published")
    with pytest.raises(ReviewActionNotAllowedError):
        PostReviewService().edit_post_texts(
            db_session, post.id, PostReviewEditRequest(telegram_text="X")
        )


def test_forbidden_transition_raises(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="rejected")
    with pytest.raises(InvalidPostStatusTransitionError):
        PostReviewService().approve_post(db_session, post.id, _DECISION)


def test_timeline_contains_actions(db_session: Session) -> None:
    project_id = _project(db_session)
    post = _post(db_session, project_id, status="draft")
    service = PostReviewService()
    service.submit_for_review(db_session, post.id, _DECISION)
    service.approve_post(db_session, post.id, _DECISION)
    timeline = service.get_timeline(db_session, post.id)
    assert timeline.current_status == "approved"
    assert [a.action for a in timeline.actions] == ["submit_for_review", "approve"]
