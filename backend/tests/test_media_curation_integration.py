"""Тесты интеграции курирования в качество и auto media selection (v0.4.8).

Offline; без live. Проверяют, что скрытые медиа исключаются из подбора и снижают качество,
восстановленное медиа снова доступно, generation_notes содержит curation summary.
"""

import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    media_curation_repository,
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
from app.services.media_quality_service import MediaQualityService
from app.services.schedule_media_decision_service import ScheduleMediaDecisionService


def _media(db: Session, project_id: int, key: str, visibility: str = "selectable") -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=f"{key}.jpg",
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status="approved",
            tags={"products": ["мерч"]},
        ),
    )
    db.commit()
    if visibility != "selectable":
        media_curation_repository.set_media_visibility(db, asset.id, visibility)
    return asset.id


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    cfg = crm.create_config(db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug))
    cat = crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id,
            config_id=cfg.id,
            title="Мерч",
            cta="Заказать",
            media_tags=["мерч"],
        ),
    )
    return account, project, cat


def test_hidden_duplicate_excluded_from_selection(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "curi-hide")
    good = _media(db_session, project.id, "good")
    _hidden = _media(db_session, project.id, "hidden", visibility="hidden_duplicate")
    svc = ScheduleMediaDecisionService(settings=Settings())
    result = svc.choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert _hidden not in result["selected_media_asset_ids"]
    assert good in result["selected_media_asset_ids"] or result["selected_media_count"] == 1
    assert result["media_curation_summary"]["hidden_media_skipped_count"] >= 1


def test_restored_media_selectable_again(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "curi-restore")
    m = _media(db_session, project.id, "m", visibility="hidden_manual")
    svc = ScheduleMediaDecisionService(settings=Settings())
    r1 = svc.choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert m not in r1["selected_media_asset_ids"]
    media_curation_repository.restore_media_visibility(db_session, m)
    r2 = svc.choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert m in r2["selected_media_asset_ids"]


def test_media_quality_sees_hidden(db_session: Session) -> None:
    _acc, project, _cat = _seed(db_session, "curi-quality")
    m = _media(db_session, project.id, "m", visibility="hidden_weak")
    result = MediaQualityService(settings=Settings()).score_media_asset(
        db_session, project.id, m, "telegram", dry_run=True
    )
    assert "hidden_from_selection" in result["issue_codes"]
    assert result["overall_score"] <= 30


def test_generation_notes_has_curation_summary(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "curi-notes")
    _media(db_session, project.id, "a")
    svc = ScheduleMediaDecisionService(settings=Settings())
    result = svc.choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert "media_curation_summary" in result
    assert "hidden_media_skipped_count" in result["media_curation_summary"]


def test_no_publish_due() -> None:
    from app.services import media_curation_service as cur_module
    from app.services import media_tag_suggestion_service as tag_module

    for mod in (cur_module, tag_module):
        source = inspect.getsource(mod)
        assert "scripts.publish_due" not in source
        assert "import publish_due" not in source
