"""Тесты сервиса курирования медиатеки (v0.4.8).

Offline; без внешнего AI/live. Проверяют preview/generate, задачи из дублей/качества/ретегинга,
apply (approve_tags/mark_duplicate/restore), идемпотентность и отсутствие удаления файлов.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    media_curation_repository,
    media_duplicate_cluster_repository,
    media_quality_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_curation_service import MediaCurationService


def _media(
    db: Session, project_id: int, key: str, file_name: str = "hoodie_dtf.jpg", tags=None
) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=file_name,
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
    return account, project


def _svc() -> MediaCurationService:
    return MediaCurationService(settings=Settings())


def test_preview_no_writes(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-prev")
    _media(db_session, project.id, "a")
    r = _svc().preview_curation_tasks(db_session, project.id, "telegram")
    assert r["dry_run"] is True
    assert r["tasks_found"] >= 1
    assert media_curation_repository.list_tasks_for_project(db_session, project.id) == []


def test_generate_creates_tasks(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-gen")
    _media(db_session, project.id, "a")
    r = _svc().generate_curation_tasks(db_session, project.id, "telegram", dry_run=False)
    assert r["tasks_created"] >= 1
    assert len(media_curation_repository.list_tasks_for_project(db_session, project.id)) >= 1


def test_generate_idempotent(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-idem")
    _media(db_session, project.id, "a")
    svc = _svc()
    svc.generate_curation_tasks(db_session, project.id, "telegram", dry_run=False)
    n1 = len(media_curation_repository.list_tasks_for_project(db_session, project.id))
    svc.generate_curation_tasks(db_session, project.id, "telegram", dry_run=False)
    n2 = len(media_curation_repository.list_tasks_for_project(db_session, project.id))
    assert n1 == n2  # тот же idempotency_key — без дублей


def test_duplicate_cluster_creates_review_task(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-dup")
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
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
    tasks = _svc().build_tasks_from_duplicate_clusters(db_session, project.id)
    assert any(t["task_type"] == "duplicate_review" for t in tasks)
    assert tasks[0]["task_metadata"]["canonical_media_asset_id"] == a


def test_weak_quality_creates_weak_task(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-weak")
    a = _media(db_session, project.id, "a")
    media_quality_repository.create_snapshot(
        db_session,
        project_id=project.id,
        media_asset_id=a,
        status="weak",
        overall_score=45,
        issue_codes=["heic_conversion_needed"],
    )
    tasks = _svc().build_tasks_from_quality_snapshots(db_session, project.id, "telegram")
    types = {t["task_type"] for t in tasks}
    assert "weak_media_review" in types
    assert "heic_conversion_needed" in types


def test_missing_tags_creates_retag_task(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-retag")
    _media(db_session, project.id, "a", file_name="hoodie_dtf.jpg", tags={})
    tasks = _svc().build_retag_tasks(db_session, project.id, "telegram")
    assert any(t["task_type"] in ("retag_suggestion", "missing_tags") for t in tasks)


def test_apply_approve_tags_updates_asset(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-apply")
    a = _media(db_session, project.id, "a", file_name="hoodie_dtf.jpg", tags={})
    svc = _svc()
    svc.generate_curation_tasks(db_session, project.id, "telegram", dry_run=False)
    task = next(
        t
        for t in media_curation_repository.list_tasks_for_project(db_session, project.id)
        if t.task_type in ("retag_suggestion", "missing_tags")
    )
    r = svc.apply_task(db_session, task.id, "approve_tags")
    assert r["outcome"] == "applied"
    asset = media_repo.get_media_asset_by_id(db_session, a)
    all_tags = [v for values in (asset.tags or {}).values() for v in values]
    assert all_tags  # теги добавлены после подтверждения
    assert asset.curation_status == "reviewed"


def test_apply_cannot_double_apply(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-double")
    _media(db_session, project.id, "a")
    svc = _svc()
    svc.generate_curation_tasks(db_session, project.id, "telegram", dry_run=False)
    task = media_curation_repository.list_tasks_for_project(db_session, project.id)[0]
    svc.apply_task(db_session, task.id, "mark_reviewed")
    r2 = svc.apply_task(db_session, task.id, "mark_reviewed")
    assert r2["outcome"] == "already_final"


def test_mark_duplicate_hides_media(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-hide")
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
    cluster = media_duplicate_cluster_repository.create_cluster(
        db_session,
        project_id=project.id,
        status="active",
        cluster_type="near_duplicate",
        canonical_media_asset_id=a,
        member_media_asset_ids=[a, b],
        member_fingerprint_ids=[],
        similarity_score=0.95,
    )
    svc = _svc()
    svc.generate_curation_tasks(db_session, project.id, "telegram", dry_run=False)
    task = next(
        t
        for t in media_curation_repository.list_tasks_for_project(db_session, project.id)
        if t.task_type == "duplicate_review"
    )
    svc.apply_task(db_session, task.id, "mark_duplicate")
    # canonical остаётся selectable, дубль скрыт.
    assert media_repo.get_media_asset_by_id(db_session, a).selection_visibility == "selectable"
    assert (
        media_repo.get_media_asset_by_id(db_session, b).selection_visibility == "hidden_duplicate"
    )
    assert cluster is not None


def test_restore_makes_selectable(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-restore")
    a = _media(db_session, project.id, "a")
    media_curation_repository.set_media_visibility(db_session, a, "hidden_manual")
    _svc().restore_media(db_session, project.id, a)
    assert media_repo.get_media_asset_by_id(db_session, a).selection_visibility == "selectable"


def test_reject_and_ignore(db_session: Session) -> None:
    _acc, project = _seed(db_session, "cur-rej")
    _media(db_session, project.id, "a")
    svc = _svc()
    svc.generate_curation_tasks(db_session, project.id, "telegram", dry_run=False)
    tasks = media_curation_repository.list_tasks_for_project(db_session, project.id)
    r = svc.reject_task(db_session, tasks[0].id, "не нужно")
    assert r["outcome"] == "rejected"
    if len(tasks) > 1:
        r2 = svc.ignore_task(db_session, tasks[1].id)
        assert r2["outcome"] == "ignored"


def test_no_delete_method() -> None:
    import inspect

    from app.services import media_curation_service as mod

    src = inspect.getsource(mod)
    assert "os.remove" not in src
    assert ".unlink(" not in src
    assert "delete_media" not in src
