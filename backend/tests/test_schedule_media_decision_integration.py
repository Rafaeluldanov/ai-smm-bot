"""Тесты интеграции автовыбора медиа в движок расписаний (v0.4.5).

Offline; никаких live-публикаций. Проверяют, что run_due пишет метаданные решения о медиа в
generation_notes и ScheduleRun.run_metadata, needs_public_image_url для Instagram/Telegram,
fallback при выключенном флаге, low_confidence, отсутствие live-публикации.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.post import Post
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    schedule_media_decision_repository,
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
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.client_learning_service import ClientLearningService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.schedule_automation_service import ScheduleAutomationService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_NOW = datetime(2026, 7, 13, 13, 0, tzinfo=UTC)  # понедельник 13:00
_TOPICS = ["Футболки лого", "Худи осень", "Акция мерч", "Кружки промо", "Стикеры"]


def _seed(  # noqa: ANN202
    db: Session,
    slug: str = "mint",
    platform: str = "telegram",
    with_media: bool = True,
    learn: bool = True,
):
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
    crm.create_plan(
        db,
        CrmPublishingPlanCreate(
            project_id=project.id,
            config_id=cfg.id,
            category_id=cat.id,
            weekdays=[0],
            publish_times=["12:00"],
            platforms=[platform],
        ),
    )
    PlatformConnectionService().upsert_connection(
        db, project.id, platform, {"api_key": _TOKEN, "external_id": "@t"}
    )
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    if with_media:
        for i in range(3):
            media_repo.create_media_asset(
                db,
                MediaAssetCreate(
                    project_id=project.id,
                    file_name="img.jpg",
                    yandex_disk_path=f"disk:/{slug}-{i}.jpg",
                    source_type="internal",
                    license_type=None,
                    status="approved",
                    tags={"products": ["мерч"], "categories": ["мерч"]},
                ),
            )
        db.commit()
    if learn:
        learner = ClientLearningService()
        for t in _TOPICS:
            post = post_repository.create_post(
                db,
                PostCreate(
                    project_id=project.id,
                    title=t,
                    status="needs_review",
                    vk_text="T",
                    hashtags=["мерч"],
                ),
            )
            db.commit()
            learner.record_review_feedback(db, post.id, "approved")
            db.commit()
        learner.build_learning_profile(db, project.id)
        db.commit()
    return account, project


def _svc(**flags: object) -> ScheduleAutomationService:
    return ScheduleAutomationService(settings=Settings(**flags))


def _on(**extra: object) -> dict[str, object]:
    return {
        "auto_media_selection_worker_enabled": True,
        "auto_media_selection_dry_run": False,
        **extra,
    }


def _latest_draft(db: Session, project_id: int) -> Post:
    return (
        db.query(Post)
        .filter(Post.project_id == project_id, Post.status == "needs_review")
        .order_by(Post.id.desc())
        .first()
    )


def test_disabled_flag_no_media_decision_but_draft(db_session: Session) -> None:
    acc, project = _seed(db_session, "mint-off")
    result = _svc().run_due(db_session, acc.id, project.id, now=_NOW)
    assert result["created"] == 1
    assert result["media_decisions_created"] == 0
    assert schedule_media_decision_repository.list_for_project(db_session, project.id) == []


def test_run_creates_media_decision_metadata(db_session: Session) -> None:
    acc, project = _seed(db_session, "mint-on")
    result = _svc(**_on()).run_due(db_session, acc.id, project.id, now=_NOW)
    assert result["created"] == 1
    assert result["media_decisions_created"] == 1
    rows = schedule_media_decision_repository.list_for_project(db_session, project.id)
    assert len(rows) == 1 and rows[0].status == "applied_to_draft"
    notes = _latest_draft(db_session, project.id).generation_notes or {}
    assert notes.get("schedule_media_decision_id") == rows[0].id
    assert notes.get("selected_media_asset_ids")
    assert notes.get("selected_media_strategy") in ("single_image", "media_group")


def test_telegram_needs_public_image_url_false(db_session: Session) -> None:
    acc, project = _seed(db_session, "mint-tg", platform="telegram")
    _svc(**_on()).run_due(db_session, acc.id, project.id, now=_NOW)
    notes = _latest_draft(db_session, project.id).generation_notes or {}
    assert notes.get("needs_public_image_url") is False


def test_instagram_needs_public_image_url_true(db_session: Session) -> None:
    acc, project = _seed(db_session, "mint-ig", platform="instagram")
    _svc(**_on()).run_due(db_session, acc.id, project.id, now=_NOW)
    notes = _latest_draft(db_session, project.id).generation_notes or {}
    assert notes.get("needs_public_image_url") is True


def test_low_confidence_media_flag(db_session: Session) -> None:
    # Категория с media_tags, но без медиа → text_only, has_media_tags=True → low confidence.
    acc, project = _seed(db_session, "mint-lc", platform="telegram", with_media=False, learn=False)
    result = _svc(**_on()).run_due(db_session, acc.id, project.id, now=_NOW)
    assert result["media_decisions_created"] == 1
    assert result["low_confidence_media_decisions"] == 1
    rows = schedule_media_decision_repository.list_for_project(db_session, project.id)
    assert "low_confidence" in (rows[0].risk_flags or [])
    assert _latest_draft(db_session, project.id).status == "needs_review"


def test_fallback_works_when_disabled(db_session: Session) -> None:
    # Флаг выключен → обычный CRM-драфт создаётся, решений о медиа нет.
    acc, project = _seed(db_session, "mint-fb")
    result = _svc().run_due(db_session, acc.id, project.id, now=_NOW)
    assert result["created"] == 1
    assert _latest_draft(db_session, project.id) is not None


def test_run_metadata_has_media_decision(db_session: Session) -> None:
    from app.repositories import schedule_run_repository

    acc, project = _seed(db_session, "mint-meta")
    _svc(**_on()).run_due(db_session, acc.id, project.id, now=_NOW)
    runs = schedule_run_repository.list_for_project(db_session, project.id)
    assert runs
    meta = runs[0].run_metadata or {}
    assert "media_decision" in meta
    assert meta["media_decision"].get("selected_strategy")


def test_no_live_publish(db_session: Session) -> None:
    from app.models.post_publication import PostPublication

    acc, project = _seed(db_session, "mint-nolive")
    _svc(**_on()).run_due(db_session, acc.id, project.id, now=_NOW)
    assert db_session.query(Post).filter(Post.status == "published").count() == 0
    for pub in db_session.query(PostPublication).all():
        assert pub.status != "published"


def test_full_auto_still_gated_with_media_decision(db_session: Session) -> None:
    acc, project = _seed(db_session, "mint-fa")
    from app.repositories import crm_bot_smm_repository as crm_repo

    config = crm_repo.get_config_by_project_id(db_session, project.id)
    plan = crm_repo.list_plans_by_config(db_session, config.id)[0]
    plan.automation_mode = "full_auto"
    plan.auto_publish_enabled = True
    plan.require_review_before_first_auto = False
    plan.min_quality_score_for_auto = 0
    db_session.commit()
    result = _svc(**_on()).run_due(db_session, acc.id, project.id, now=_NOW)
    assert result["media_decisions_created"] == 1
    # Live выключен → авто-публикация заблокирована, пост needs_review, ничего не published.
    assert db_session.query(Post).filter(Post.status == "published").count() == 0
    assert _latest_draft(db_session, project.id).status == "needs_review"
