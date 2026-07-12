"""Тесты сервиса автовыбора медиа (v0.4.5).

Offline, без внешних API и live-публикаций. Проверяют кандидатов, скоринг, выбор стратегии,
объяснение, запись решения, штрафы (recent/fatigue), fallback, изоляцию проектов и отсутствие
секретов/внутренних путей в метаданных.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    content_experiment_repository,
    post_repository,
    project_repository,
    schedule_media_decision_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.client_learning_service import ClientLearningService
from app.services.schedule_media_decision_service import ScheduleMediaDecisionService
from app.services.schedule_topic_decision_service import ScheduleTopicDecisionService

_TOPICS = ["Футболки лого", "Худи осень", "Акция мерч", "Кружки промо", "Стикеры"]


def _media(
    db: Session,
    project_id: int,
    key: str,
    tags: dict | None = None,
    status: str = "approved",
    file_name: str = "img.jpg",
) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=file_name,
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status=status,
            tags=tags if tags is not None else {"products": ["мерч"], "categories": ["мерч"]},
        ),
    )
    db.commit()
    return asset.id


def _seed(db: Session, slug: str, approve: bool = True, media_count: int = 3):  # noqa: ANN202
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
    for i in range(media_count):
        _media(db, project.id, f"{slug}-{i}")
    learn = ClientLearningService()
    if approve:
        for t in _TOPICS:
            post = post_repository.create_post(
                db,
                PostCreate(
                    project_id=project.id,
                    title=t,
                    status="needs_review",
                    vk_text="Текст " + t,
                    hashtags=["мерч"],
                ),
            )
            db.commit()
            learn.record_review_feedback(db, post.id, "approved")
            db.commit()
        learn.build_learning_profile(db, project.id)
        db.commit()
    return account, project, cat


def _svc(**flags: object) -> ScheduleMediaDecisionService:
    return ScheduleMediaDecisionService(settings=Settings(**flags))


def test_preview_no_writes(db_session: Session) -> None:
    _acc, project, _cat = _seed(db_session, "md-prev")
    result = _svc().preview_media_decision_for_plan(db_session, project.id, "telegram")
    assert result["writes"] is False
    assert result["selected_strategy"] in (
        "text_only",
        "single_image",
        "media_group",
        "carousel_ready",
        "video_later",
        "no_media_available",
    )
    assert schedule_media_decision_repository.list_for_project(db_session, project.id) == []


def test_create_decision_writes_row(db_session: Session) -> None:
    _acc, project, _cat = _seed(db_session, "md-create")
    result = _svc().create_media_decision_for_plan(db_session, project.id, "telegram")
    assert result["outcome"] == "created"
    rows = schedule_media_decision_repository.list_for_project(db_session, project.id)
    assert len(rows) == 1
    assert rows[0].status == "selected"
    assert rows[0].selected_media_count >= 1


def test_decision_uses_crm_category_media_tags(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "md-tags")
    result = _svc().choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["selected_media_count"] >= 1
    assert "мерч" in result["selected_media_tags"]
    assert result["decision_source"] in ("media_tags", "learning_profile")


def test_decision_links_topic_decision(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "md-topic")
    topic = ScheduleTopicDecisionService(settings=Settings()).create_decision_for_plan(
        db_session, project.id, "telegram", category_id=cat.id
    )
    result = _svc().create_media_decision_for_plan(
        db_session, project.id, "telegram", topic_decision_id=topic["id"]
    )
    row = schedule_media_decision_repository.get_by_id(db_session, result["id"])
    assert row.schedule_topic_decision_id == topic["id"]


def test_media_group_strategy_for_multiple_images(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "md-group", media_count=4)
    result = _svc().choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["selected_strategy"] == "media_group"
    assert result["selected_media_count"] >= 2


def test_single_image_strategy_for_one_image(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "md-single", media_count=1)
    result = _svc().choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["selected_strategy"] == "single_image"
    assert result["selected_media_count"] == 1


def test_instagram_needs_public_image_url(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "md-ig")
    result = _svc().choose_media_for_schedule(db_session, project.id, "instagram", category=cat)
    assert result["needs_public_image_url"] is True
    assert "platform_requires_public_url" in result["risk_flags"]
    assert result["selected_strategy"] in ("single_image", "carousel_ready")


def test_telegram_no_public_image_url(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "md-tg")
    result = _svc().choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["needs_public_image_url"] is False


def test_no_media_returns_no_media_available_for_instagram(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "md-noig", media_count=0)
    result = _svc().choose_media_for_schedule(db_session, project.id, "instagram", category=cat)
    assert result["selected_strategy"] == "no_media_available"
    assert result["selected_media_count"] == 0


def test_no_media_returns_text_only_for_telegram(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "md-notg", media_count=0)
    result = _svc().choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["selected_strategy"] == "text_only"
    assert result["selected_media_count"] == 0


def test_decision_uses_ab_winner_strategy(db_session: Session) -> None:
    acc, project, _cat = _seed(db_session, "md-ab")
    exp = content_experiment_repository.create_experiment(
        db_session,
        account_id=acc.id,
        project_id=project.id,
        platform_key="telegram",
        experiment_type="ab_test",
        title="Медиа-победитель",
        status="completed",
    )
    content_experiment_repository.create_variant(
        db_session,
        experiment_id=exp.id,
        account_id=acc.id,
        project_id=project.id,
        variant_key="A",
        title="Победитель",
        cta_type="Жми",
        media_strategy="media_group",
        is_winner=True,
        winner_reason="higher_er",
        quality_score=90,
    )
    ctx = _svc()._build_context(db_session, project.id, "telegram", None, None)
    assert ctx["ab_strategy"] == "media_group"
    assert "ab_winner" in ctx["signals"]


def test_high_performing_media_tags_boost_score(db_session: Session) -> None:
    _acc, project, _cat = _seed(db_session, "md-high", media_count=0)
    aid = _media(db_session, project.id, "gold", tags={"products": ["gold"]})
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    svc = _svc()
    base_ctx = {
        "wanted_tags": set(),
        "topic_tokens": set(),
        "category_tags": set(),
        "high_media_tags": set(),
        "recent_media_ids": set(),
        "platform_video_ok": False,
        "variant_by_asset": {},
    }
    low = svc.score_media_candidate(db_session, project.id, "telegram", asset, base_ctx)
    hi = svc.score_media_candidate(
        db_session, project.id, "telegram", asset, {**base_ctx, "high_media_tags": {"gold"}}
    )
    assert hi["breakdown"]["high_perf"] == 15
    assert hi["score"] > low["score"]


def test_recent_media_penalized(db_session: Session) -> None:
    _acc, project, _cat = _seed(db_session, "md-recent", media_count=0)
    aid = _media(db_session, project.id, "reuse")
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    svc = _svc()
    base_ctx = {
        "wanted_tags": set(),
        "topic_tokens": set(),
        "category_tags": set(),
        "high_media_tags": set(),
        "recent_media_ids": set(),
        "platform_video_ok": False,
        "variant_by_asset": {},
    }
    fresh = svc.score_media_candidate(db_session, project.id, "telegram", asset, base_ctx)
    recent = svc.score_media_candidate(
        db_session, project.id, "telegram", asset, {**base_ctx, "recent_media_ids": {aid}}
    )
    assert fresh["breakdown"]["novelty"] > 0
    assert recent["breakdown"]["novelty"] < 0
    assert recent["score"] < fresh["score"]


def test_fallback_to_approved_media(db_session: Session) -> None:
    # Медиа без совпадающих тегов → fallback к любым approved (не пустой пул).
    _acc, project, cat = _seed(db_session, "md-fallback", media_count=0)
    _media(db_session, project.id, "misc", tags={"products": ["нечто-иное"]})
    images, _videos, pool = _svc().build_media_candidates(
        db_session, project.id, "telegram", category=cat
    )
    assert len(pool) >= 1
    assert len(images) >= 1
    result = _svc().choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["selected_strategy"] in ("single_image", "media_group")


def test_confidence_in_range(db_session: Session) -> None:
    _acc, project, _cat = _seed(db_session, "md-conf")
    result = _svc().preview_media_decision_for_plan(db_session, project.id, "telegram")
    assert 0.0 <= result["confidence_score"] <= 1.0


def test_create_decision_idempotent(db_session: Session) -> None:
    _acc, project, _cat = _seed(db_session, "md-idem")
    svc = _svc()
    first = svc.create_media_decision_for_plan(
        db_session, project.id, "telegram", idempotency_key="k1"
    )
    second = svc.create_media_decision_for_plan(
        db_session, project.id, "telegram", idempotency_key="k1"
    )
    assert first["id"] == second["id"]
    assert second["outcome"] == "skipped_duplicate"
    assert len(schedule_media_decision_repository.list_for_project(db_session, project.id)) == 1


def test_project_isolation(db_session: Session) -> None:
    _a1, p1, _c1 = _seed(db_session, "md-iso1")
    _a2, p2, _c2 = _seed(db_session, "md-iso2")
    _svc().create_media_decision_for_plan(db_session, p1.id, "telegram")
    assert schedule_media_decision_repository.list_for_project(db_session, p2.id) == []
    assert len(schedule_media_decision_repository.list_for_project(db_session, p1.id)) == 1


def test_no_secrets_or_paths_in_metadata(db_session: Session) -> None:
    from app.services.platform_connection_service import PlatformConnectionService

    _acc, project, _cat = _seed(db_session, "md-nosec")
    secret = "123456789:svcSECRETmediaTOKEN"
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": secret, "external_id": "@t"}
    )
    db_session.commit()
    result = _svc().create_media_decision_for_plan(db_session, project.id, "telegram")
    row = schedule_media_decision_repository.get_by_id(db_session, result["id"])
    blob = (
        str(row.decision_metadata)
        + str(row.source_signals)
        + str(row.reasons)
        + str(row.alternatives)
        + str(row.selected_media_tags)
    )
    assert secret not in blob
    assert "api_key" not in blob
    assert "token" not in blob.lower()
    # Внутренние пути к файлам не утекают в решение.
    assert "disk:/" not in blob
    assert "img.jpg" not in blob
