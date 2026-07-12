"""Тесты интеграции уведомлений в collaborative review медиатеки (v0.5.0). Offline."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    media_curation_repository,
    notification_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import media_asset_repository as media_repo
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_curation_review_service import MediaCurationReviewService
from app.services.media_curation_service import MediaCurationService


def _media(db: Session, project_id: int, key: str) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="hoodie_dtf.jpg",
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status="approved",
            tags={},
        ),
    )
    db.commit()
    return asset.id


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}-own@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    assignee = user_repository.create_user(db, email=f"{slug}-rev@e.com", password_hash="x")
    account_repository.create_membership(db, account.id, assignee.id, role="member")
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    cfg = crm.create_config(db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug))
    crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id,
            config_id=cfg.id,
            title="Мерч",
            cta="Заказать",
            media_tags=["мерч"],
        ),
    )
    _media(db, project.id, f"{slug}-a")
    MediaCurationService().generate_curation_tasks(db, project.id, "telegram", dry_run=False)
    task = next(
        t
        for t in media_curation_repository.list_tasks_for_project(db, project.id)
        if t.task_type in ("retag_suggestion", "missing_tags")
    )
    return account, project, owner, assignee, task


def _svc(s: Settings) -> MediaCurationReviewService:
    return MediaCurationReviewService(curation_service=MediaCurationService(settings=s), settings=s)


def test_assign_creates_notification(db_session: Session) -> None:
    _account, project, owner, assignee, task = _seed(db_session, "rn-assign")
    _svc(Settings()).assign_task(db_session, task.id, assignee.id, current_user_id=owner.id)
    notes = notification_repository.list_for_user(db_session, assignee.id)
    assert any(n.notification_type == "review_assigned" for n in notes)


def test_comment_creates_notification(db_session: Session) -> None:
    _account, project, owner, assignee, task = _seed(db_session, "rn-comment")
    svc = _svc(Settings())
    svc.assign_task(db_session, task.id, assignee.id, current_user_id=owner.id)
    svc.add_comment(db_session, task.id, "Проверьте, пожалуйста", current_user_id=owner.id)
    notes = notification_repository.list_for_user(db_session, assignee.id)
    assert any(n.notification_type == "review_comment" for n in notes)


def test_mention_creates_mention_and_notification(db_session: Session) -> None:
    account, project, owner, assignee, task = _seed(db_session, "rn-mention")
    svc = _svc(Settings())
    svc.add_comment(
        db_session, task.id, f"@{assignee.email} посмотри задачу", current_user_id=owner.id
    )
    mentions = notification_repository.list_mentions_for_entity(
        db_session, "media_curation_task", str(task.id)
    )
    assert any(m.mentioned_user_id == assignee.id and m.status == "notified" for m in mentions)
    notes = notification_repository.list_for_user(db_session, assignee.id)
    assert any(n.notification_type == "review_mentioned" for n in notes)


def test_unresolved_mention_stored(db_session: Session) -> None:
    account, project, owner, _assignee, task = _seed(db_session, "rn-unres")
    svc = _svc(Settings())
    # Комментарий не роняется, упоминание сохраняется как unresolved.
    out = svc.add_comment(db_session, task.id, "@nobody@ghost.com глянь", current_user_id=owner.id)
    assert out["id"] >= 1
    mentions = notification_repository.list_mentions_for_entity(
        db_session, "media_curation_task", str(task.id)
    )
    assert any(m.status == "unresolved" for m in mentions)


def test_approve_reject_apply_notify(db_session: Session) -> None:
    _account, project, owner, assignee, task = _seed(db_session, "rn-status")
    svc = _svc(Settings())
    svc.assign_task(db_session, task.id, assignee.id, current_user_id=owner.id)
    svc.approve_task(db_session, task.id, current_user_id=owner.id)
    svc.apply_approved_task(db_session, task.id, "approve_tags", current_user_id=owner.id)
    notes = notification_repository.list_for_user(db_session, assignee.id)
    types = {n.notification_type for n in notes}
    assert "review_approved" in types
    assert "review_applied" in types


def test_no_notification_when_actor_is_assignee(db_session: Session) -> None:
    _account, project, owner, assignee, task = _seed(db_session, "rn-self")
    svc = _svc(Settings())
    # assignee назначает сам себя → не уведомляем самого себя.
    svc.assign_task(db_session, task.id, assignee.id, current_user_id=assignee.id)
    notes = notification_repository.list_for_user(db_session, assignee.id)
    assert not any(n.notification_type == "review_assigned" for n in notes)


def test_no_duplicate_spam(db_session: Session) -> None:
    _account, project, owner, assignee, task = _seed(db_session, "rn-dedup")
    svc = _svc(Settings())
    svc.assign_task(db_session, task.id, assignee.id, current_user_id=owner.id)
    # Повторные комментарии в окне дедупликации не плодят review_comment.
    svc.add_comment(db_session, task.id, "первый", current_user_id=owner.id)
    svc.add_comment(db_session, task.id, "второй", current_user_id=owner.id)
    notes = notification_repository.list_for_user(db_session, assignee.id)
    comment_notes = [n for n in notes if n.notification_type == "review_comment"]
    assert len(comment_notes) == 1
