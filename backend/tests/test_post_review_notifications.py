"""Тесты интеграции уведомлений в review workflow постов (v0.5.0). Offline."""

from sqlalchemy.orm import Session

from app.models.post import Post
from app.repositories import (
    account_repository,
    notification_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.post import PostCreate
from app.schemas.post_review import PostReviewDecisionRequest
from app.schemas.project import ProjectCreate
from app.services.post_review_service import PostReviewService
from app.services.review_workflow_service import ReviewWorkflowService

_DECISION = PostReviewDecisionRequest(actor_name="Reviewer")


def _seed(db: Session, slug: str, with_account: bool = True):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    if with_account:
        account = account_repository.create_account(
            db, name=slug, slug=slug, owner_user_id=owner.id
        )
        project.account_id = account.id
        db.commit()
    return owner, project


def _post(db: Session, project_id: int, status: str = "draft") -> Post:
    media_id = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="f.jpg",
            yandex_disk_path="disk:/f.jpg",
            status="approved",
            tags={"products": ["футболка"]},
        ),
    ).id
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
            seo_keywords=["ф"],
            status=status,
        ),
    )


def test_submit_creates_needs_review_notification(db_session: Session) -> None:
    owner, project = _seed(db_session, "pn-submit")
    post = _post(db_session, project.id)
    PostReviewService().submit_for_review(db_session, post.id, _DECISION)
    notes = notification_repository.list_for_user(db_session, owner.id)
    assert any(n.notification_type == "post_needs_review" for n in notes)


def test_approve_creates_notification_when_recipient_known(db_session: Session) -> None:
    owner, project = _seed(db_session, "pn-approve")
    post = _post(db_session, project.id, status="needs_review")
    ReviewWorkflowService().approve(db_session, post.id, _DECISION, user_id=None)
    notes = notification_repository.list_for_user(db_session, owner.id)
    assert any(n.notification_type == "post_approved" for n in notes)


def test_reject_creates_notification(db_session: Session) -> None:
    owner, project = _seed(db_session, "pn-reject")
    post = _post(db_session, project.id, status="needs_review")
    ReviewWorkflowService().reject(db_session, post.id, _DECISION, user_id=None)
    notes = notification_repository.list_for_user(db_session, owner.id)
    assert any(n.notification_type == "post_rejected" for n in notes)


def test_no_recipient_skip_no_failure(db_session: Session) -> None:
    # Проект без аккаунта → получателя нет → пропускаем без ошибки.
    _owner, project = _seed(db_session, "pn-norec", with_account=False)
    post = _post(db_session, project.id)
    # Не должно бросать исключение.
    card = PostReviewService().submit_for_review(db_session, post.id, _DECISION)
    assert card.status == "needs_review"


def test_self_action_no_self_notification(db_session: Session) -> None:
    owner, project = _seed(db_session, "pn-self")
    post = _post(db_session, project.id, status="needs_review")
    # Владелец сам одобряет → себе уведомление не шлём.
    ReviewWorkflowService().approve(db_session, post.id, _DECISION, user_id=owner.id)
    notes = notification_repository.list_for_user(db_session, owner.id)
    assert not any(n.notification_type == "post_approved" for n in notes)
