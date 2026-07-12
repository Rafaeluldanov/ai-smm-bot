"""Тесты сервиса collaborative review курирования медиатеки (v0.4.9).

Offline; без внешнего AI/live. Проверяют workflow (assign/start/approve/reject/apply),
approval-before-apply, double-apply, комментарии/timeline, санитизацию и отсутствие удаления.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    media_curation_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import media_asset_repository as media_repo
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_curation_review_service import (
    MediaCurationReviewService,
    sanitize_review_text,
)
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


def _svc(settings: Settings | None = None) -> MediaCurationReviewService:
    s = settings or Settings()
    return MediaCurationReviewService(curation_service=MediaCurationService(settings=s), settings=s)


def _gen_retag_task(db: Session, project_id: int, settings: Settings):  # noqa: ANN202
    MediaCurationService(settings=settings).generate_curation_tasks(
        db, project_id, "telegram", dry_run=False
    )
    return next(
        t
        for t in media_curation_repository.list_tasks_for_project(db, project_id)
        if t.task_type in ("retag_suggestion", "missing_tags")
    )


def test_generated_tasks_start_proposed(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-prop")
    _media(db_session, project.id, "a")
    s = Settings()
    task = _gen_retag_task(db_session, project.id, s)
    assert task.review_status == "proposed"
    assert task.priority == "normal"


def test_dashboard_counts_statuses(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-dash")
    _media(db_session, project.id, "a")
    s = Settings()
    _gen_retag_task(db_session, project.id, s)
    dash = _svc(s).build_review_dashboard(db_session, project.id)
    assert dash["proposed"] >= 1
    assert dash["active_review_tasks"] >= 1
    assert dash["require_approval"] is True
    assert dash["auto_apply_after_approval"] is False


def test_add_comment(db_session: Session) -> None:
    _a, project, user = _seed(db_session, "rv-comment")
    _media(db_session, project.id, "a")
    s = Settings()
    task = _gen_retag_task(db_session, project.id, s)
    svc = _svc(s)
    out = svc.add_comment(db_session, task.id, "Оставить главное фото", current_user_id=user.id)
    assert out["id"] >= 1
    assert out["comment_text"] == "Оставить главное фото"
    comments = svc.list_comments(db_session, project.id, task.id)
    assert any(c["comment_text"] == "Оставить главное фото" for c in comments)


def test_assign_task(db_session: Session) -> None:
    _a, project, user = _seed(db_session, "rv-assign")
    _media(db_session, project.id, "a")
    s = Settings()
    task = _gen_retag_task(db_session, project.id, s)
    r = _svc(s).assign_task(db_session, task.id, user.id, priority="high")
    assert r["outcome"] == "assigned"
    db_session.refresh(task)
    assert task.assignee_user_id == user.id
    assert task.review_status == "assigned"
    assert task.priority == "high"


def test_start_review(db_session: Session) -> None:
    _a, project, user = _seed(db_session, "rv-start")
    _media(db_session, project.id, "a")
    s = Settings()
    task = _gen_retag_task(db_session, project.id, s)
    _svc(s).start_review(db_session, task.id, current_user_id=user.id)
    db_session.refresh(task)
    assert task.review_status == "in_review"
    assert task.reviewer_user_id == user.id


def test_request_changes(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-changes")
    _media(db_session, project.id, "a")
    s = Settings()
    task = _gen_retag_task(db_session, project.id, s)
    _svc(s).request_changes(db_session, task.id, "Добавьте технологию печати")
    db_session.refresh(task)
    assert task.review_status == "changes_requested"
    assert task.changes_requested_at is not None


def test_approve_task_does_not_apply(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-approve")
    aid = _media(db_session, project.id, "a")
    s = Settings()
    task = _gen_retag_task(db_session, project.id, s)
    r = _svc(s).approve_task(db_session, task.id, comment="Теги корректные")
    assert r["outcome"] == "approved"
    assert r["auto_applied"] is False
    db_session.refresh(task)
    assert task.review_status == "approved"
    assert task.approved_at is not None
    # Теги ещё НЕ применены (нужен отдельный apply).
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    assert not [v for values in (asset.tags or {}).values() for v in values]


def test_reject_task_does_not_apply(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-reject")
    aid = _media(db_session, project.id, "a")
    s = Settings()
    task = _gen_retag_task(db_session, project.id, s)
    r = _svc(s).reject_task(db_session, task.id, reason="не нужно")
    assert r["outcome"] == "rejected"
    db_session.refresh(task)
    assert task.review_status == "rejected"
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    assert not [v for values in (asset.tags or {}).values() for v in values]


def test_apply_unapproved_blocked(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-blocked")
    aid = _media(db_session, project.id, "a")
    s = Settings()  # require_approval=True по умолчанию
    task = _gen_retag_task(db_session, project.id, s)
    r = _svc(s).apply_approved_task(db_session, task.id, "approve_tags")
    assert r["outcome"] == "requires_approval"
    assert r["blocked"] is True
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    assert not [v for values in (asset.tags or {}).values() for v in values]


def test_apply_approved_task_works(db_session: Session) -> None:
    _a, project, user = _seed(db_session, "rv-apply")
    aid = _media(db_session, project.id, "a")
    s = Settings()
    svc = _svc(s)
    task = _gen_retag_task(db_session, project.id, s)
    svc.approve_task(db_session, task.id, current_user_id=user.id)
    r = svc.apply_approved_task(db_session, task.id, "approve_tags", current_user_id=user.id)
    assert r["outcome"] == "applied"
    db_session.refresh(task)
    assert task.review_status == "applied"
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    assert [v for values in (asset.tags or {}).values() for v in values]
    # before/after зафиксированы.
    assert task.before_state.get("media")
    assert task.after_state.get("media")
    assert task.decision_summary.get("action") == "approve_tags"


def test_double_apply_blocked(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-double")
    _media(db_session, project.id, "a")
    s = Settings()
    svc = _svc(s)
    task = _gen_retag_task(db_session, project.id, s)
    svc.approve_task(db_session, task.id)
    svc.apply_approved_task(db_session, task.id, "approve_tags")
    r2 = svc.apply_approved_task(db_session, task.id, "approve_tags")
    assert r2["outcome"] == "already_applied"
    assert r2["blocked"] is True


def test_auto_apply_after_approval_when_enabled(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-autoapply")
    aid = _media(db_session, project.id, "a")
    s = Settings(media_curation_review_auto_apply_after_approval=True)
    svc = _svc(s)
    task = _gen_retag_task(db_session, project.id, s)
    r = svc.approve_task(db_session, task.id)
    assert r["auto_applied"] is True
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    assert [v for values in (asset.tags or {}).values() for v in values]


def test_self_approval_blocked_when_disabled(db_session: Session) -> None:
    _a, project, user = _seed(db_session, "rv-selfapp")
    _media(db_session, project.id, "a")
    s = Settings(media_curation_review_allow_self_approval=False)
    svc = _svc(s)
    task = _gen_retag_task(db_session, project.id, s)
    svc.assign_task(db_session, task.id, user.id)
    r = svc.approve_task(db_session, task.id, current_user_id=user.id)
    assert r["outcome"] == "blocked"
    assert r["reason"] == "self_approval_disabled"


def test_timeline_includes_comments_and_events(db_session: Session) -> None:
    _a, project, user = _seed(db_session, "rv-timeline")
    _media(db_session, project.id, "a")
    s = Settings()
    svc = _svc(s)
    task = _gen_retag_task(db_session, project.id, s)
    svc.assign_task(db_session, task.id, user.id)
    svc.add_comment(db_session, task.id, "Комментарий ревьюера", current_user_id=user.id)
    svc.approve_task(db_session, task.id)
    detail = svc.get_task_detail(db_session, project.id, task.id)
    kinds = {e["kind"] for e in detail["timeline"]}
    assert "created" in kinds
    assert "assigned" in kinds
    assert "approved" in kinds
    assert "comment" in kinds
    assert any(c["comment_text"] == "Комментарий ревьюера" for c in detail["comments"])


def test_restore_task_media(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-restore")
    aid = _media(db_session, project.id, "a")
    s = Settings()
    svc = _svc(s)
    task = _gen_retag_task(db_session, project.id, s)  # задача на selectable-медиа
    # Позже медиа скрыли — restore возвращает его в подбор через задачу.
    media_curation_repository.set_media_visibility(db_session, aid, "hidden_manual")
    r = svc.restore_task_media(db_session, task.id)
    assert r["outcome"] == "restored"
    assert aid in r["restored_media_asset_ids"]
    assert media_repo.get_media_asset_by_id(db_session, aid).selection_visibility == "selectable"


def test_comment_sanitizes_secrets_and_paths() -> None:
    text = "token=123456789:ABCDEFghijklmnopqrstuvwxyz012345 файл disk:/secret/photo.jpg"
    cleaned = sanitize_review_text(text)
    assert "123456789:ABCDEFghijklmnopqrstuvwxyz012345" not in cleaned
    assert "disk:/secret/photo.jpg" not in cleaned


def test_comment_no_secrets_stored(db_session: Session) -> None:
    _a, project, _u = _seed(db_session, "rv-nosec")
    _media(db_session, project.id, "a")
    s = Settings()
    svc = _svc(s)
    task = _gen_retag_task(db_session, project.id, s)
    svc.add_comment(db_session, task.id, "secret token=123456789:ABCDEFghijklmnop012345678901234")
    comments = svc.list_comments(db_session, project.id, task.id)
    joined = " ".join(c["comment_text"] for c in comments)
    assert "123456789:ABCDEFghijklmnop012345678901234" not in joined


def test_no_delete_method() -> None:
    import inspect

    from app.services import media_curation_review_service as mod

    src = inspect.getsource(mod)
    assert "os.remove" not in src
    assert ".unlink(" not in src
    assert "shutil.rmtree" not in src
