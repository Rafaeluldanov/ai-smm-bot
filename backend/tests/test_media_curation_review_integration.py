"""Тесты интеграции collaborative review курирования (v0.4.9, offline, без live).

Проверяют: задачи стартуют proposed; прямой apply требует approval; approve→apply меняет
теги/видимость; rejected не применяет; комментарии в timeline; создаются audit-события.
"""

import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    audit_log_repository,
    media_curation_repository,
    media_duplicate_cluster_repository,
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


def _media(db: Session, project_id: int, key: str, tags=None) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="hoodie_dtf.jpg",
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status="approved",
            tags=tags if tags is not None else {},
        ),
    )
    db.commit()
    return asset.id


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
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
    return account, project, user


def _svc(s: Settings) -> MediaCurationReviewService:
    return MediaCurationReviewService(curation_service=MediaCurationService(settings=s), settings=s)


def _retag_task(db: Session, project_id: int, s: Settings):  # noqa: ANN202
    MediaCurationService(settings=s).generate_curation_tasks(
        db, project_id, "telegram", dry_run=False
    )
    return next(
        t
        for t in media_curation_repository.list_tasks_for_project(db, project_id)
        if t.task_type in ("retag_suggestion", "missing_tags")
    )


def test_generated_tasks_start_proposed(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rvi-prop")
    _media(db_session, project.id, "a")
    task = _retag_task(db_session, project.id, Settings())
    assert task.review_status == "proposed"


def test_direct_apply_requires_approval_by_default(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rvi-direct")
    aid = _media(db_session, project.id, "a")
    s = Settings()  # require_approval=True
    task = _retag_task(db_session, project.id, s)
    # Прямой v0.4.8 apply теперь заблокирован approval-гейтом.
    r = MediaCurationService(settings=s).apply_task(db_session, task.id, "approve_tags")
    assert r["outcome"] == "requires_approval"
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    assert not [v for values in (asset.tags or {}).values() for v in values]


def test_approval_then_apply_changes_tags(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rvi-tags")
    aid = _media(db_session, project.id, "a")
    s = Settings()
    svc = _svc(s)
    task = _retag_task(db_session, project.id, s)
    svc.approve_task(db_session, task.id)
    svc.apply_approved_task(db_session, task.id, "approve_tags")
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    assert [v for values in (asset.tags or {}).values() for v in values]
    assert asset.curation_status == "reviewed"


def test_approval_then_apply_changes_visibility(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rvi-vis")
    a = _media(db_session, project.id, "a", tags={"products": ["мерч"]})
    b = _media(db_session, project.id, "b", tags={"products": ["мерч"]})
    media_duplicate_cluster_repository.create_cluster(
        db_session,
        project_id=project.id,
        status="active",
        cluster_type="near_duplicate",
        canonical_media_asset_id=a,
        member_media_asset_ids=[a, b],
        member_fingerprint_ids=[],
        similarity_score=0.95,
    )
    s = Settings()
    svc = _svc(s)
    MediaCurationService(settings=s).generate_curation_tasks(
        db_session, project.id, "telegram", dry_run=False
    )
    task = next(
        t
        for t in media_curation_repository.list_tasks_for_project(db_session, project.id)
        if t.task_type == "duplicate_review"
    )
    svc.approve_task(db_session, task.id)
    svc.apply_approved_task(db_session, task.id, "mark_duplicate")
    assert media_repo.get_media_asset_by_id(db_session, a).selection_visibility == "selectable"
    assert (
        media_repo.get_media_asset_by_id(db_session, b).selection_visibility == "hidden_duplicate"
    )


def test_rejected_task_does_not_apply(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rvi-rej")
    aid = _media(db_session, project.id, "a")
    s = Settings()
    svc = _svc(s)
    task = _retag_task(db_session, project.id, s)
    svc.reject_task(db_session, task.id)
    # Даже после reject apply заблокирован (review_status != approved).
    r = svc.apply_approved_task(db_session, task.id, "approve_tags")
    assert r["outcome"] in ("requires_approval", "already_applied")
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    assert not [v for values in (asset.tags or {}).values() for v in values]


def test_comments_appear_in_timeline(db_session: Session) -> None:
    _a, project, user = _seed(db_session, "rvi-timeline")
    _media(db_session, project.id, "a")
    s = Settings()
    svc = _svc(s)
    task = _retag_task(db_session, project.id, s)
    svc.add_comment(db_session, task.id, "Комментарий в timeline", current_user_id=user.id)
    detail = svc.get_task_detail(db_session, project.id, task.id)
    assert any(
        e["kind"] == "comment" and e.get("comment_text") == "Комментарий в timeline"
        for e in detail["timeline"]
    )


def test_audit_events_created(db_session: Session) -> None:
    account, project, user = _seed(db_session, "rvi-audit")
    _media(db_session, project.id, "a")
    s = Settings()
    svc = _svc(s)
    task = _retag_task(db_session, project.id, s)
    svc.assign_task(db_session, task.id, user.id)
    svc.approve_task(db_session, task.id)
    svc.apply_approved_task(db_session, task.id, "approve_tags")
    actions = {
        e.action for e in audit_log_repository.list_for_account(db_session, account.id, limit=200)
    }
    assert "media_curation_review.assigned" in actions
    assert "media_curation_review.approved" in actions
    assert "media_curation_review.applied" in actions


def test_no_publish_due() -> None:
    from app.services import media_curation_review_service as mod

    source = inspect.getsource(mod)
    assert "scripts.publish_due" not in source
    assert "import publish_due" not in source
