"""Тесты интеграции оценки качества медиа в auto media selection (v0.4.6).

Offline; никаких live-публикаций. Проверяют, что решение о медиа предпочитает более
качественные ассеты, добавляет warning для слабых/повторов, пишет media_quality_summary в
generation_notes, и не тянет publish_due.
"""

import inspect
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.post import Post
from app.repositories import (
    account_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.schedule_automation_service import ScheduleAutomationService
from app.services.schedule_media_decision_service import ScheduleMediaDecisionService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_NOW = datetime(2026, 7, 13, 13, 0, tzinfo=UTC)


def _media(db: Session, project_id: int, key: str, tags: dict, file_name: str = "img.jpg") -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=file_name,
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status="approved",
            tags=tags,
        ),
    )
    db.commit()
    return asset.id


def _seed(db: Session, slug: str, with_plan: bool = False):  # noqa: ANN202
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
    if with_plan:
        crm.create_plan(
            db,
            CrmPublishingPlanCreate(
                project_id=project.id,
                config_id=cfg.id,
                category_id=cat.id,
                weekdays=[0],
                publish_times=["12:00"],
                platforms=["telegram"],
            ),
        )
        PlatformConnectionService().upsert_connection(
            db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@t"}
        )
        BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    return account, project, cat


def test_decision_prefers_higher_quality(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "mqi-pref")
    # Оба матчат тег «мерч», но strong — чистый JPEG с богатыми тегами, weak — HEIC.
    strong = _media(
        db_session,
        project.id,
        "strong",
        {"products": ["мерч"], "technologies": ["dtf"], "categories": ["мерч"]},
        file_name="strong.jpg",
    )
    _weak = _media(db_session, project.id, "weak", {"products": ["мерч"]}, file_name="weak.heic")
    svc = ScheduleMediaDecisionService(settings=Settings())
    result = svc.choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["selected_media_asset_ids"][0] == strong  # сильное медиа выбрано первым
    assert "media_quality_summary" in result
    assert result["media_quality_summary"]["selected_media_scores"]


def test_weak_media_warning(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "mqi-weak")
    # Единственное медиа: HEIC без тегов → fallback, слабое качество (overall < 70) → warning.
    _media(db_session, project.id, "w", {}, file_name="w.heic")
    svc = ScheduleMediaDecisionService(settings=Settings())
    result = svc.choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    summary = result["media_quality_summary"]
    assert summary["weak_selected_count"] >= 1
    assert "weak_media_quality" in result["risk_flags"]


def test_instagram_public_url_warning(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "mqi-ig")
    _media(db_session, project.id, "a", {"products": ["мерч"]}, file_name="a.jpg")
    svc = ScheduleMediaDecisionService(settings=Settings())
    result = svc.choose_media_for_schedule(db_session, project.id, "instagram", category=cat)
    assert result["needs_public_image_url"] is True
    assert "platform_requires_public_url" in result["risk_flags"]


def test_generation_notes_has_quality_summary(db_session: Session) -> None:
    acc, project, _cat = _seed(db_session, "mqi-notes", with_plan=True)
    _media(db_session, project.id, "a", {"products": ["мерч"]}, file_name="a.jpg")
    svc = ScheduleAutomationService(
        settings=Settings(
            auto_media_selection_worker_enabled=True, auto_media_selection_dry_run=False
        )
    )
    result = svc.run_due(db_session, acc.id, project.id, now=_NOW)
    assert result["media_decisions_created"] == 1
    draft = (
        db_session.query(Post)
        .filter(Post.project_id == project.id, Post.status == "needs_review")
        .order_by(Post.id.desc())
        .first()
    )
    notes = draft.generation_notes or {}
    assert "media_quality_summary" in notes
    assert "selected_media_scores" in notes["media_quality_summary"]


def test_no_publish_due() -> None:
    from app.services import media_quality_service as quality_module
    from app.services import schedule_media_decision_service as decision_module

    for mod in (quality_module, decision_module):
        source = inspect.getsource(mod)
        assert "scripts.publish_due" not in source
        assert "import publish_due" not in source
