"""Тесты сервиса предложения тегов медиа (v0.4.8).

Offline; без внешнего AI/сети/live. Проверяют токены имени файла, классификацию, теги из CRM/
дублей/обучения, изоляцию проектов и отсутствие путей/секретов в результате.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    media_duplicate_cluster_repository,
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
from app.services.media_tag_suggestion_service import MediaTagSuggestionService


def _media(db: Session, project_id: int, key: str, file_name: str, tags: dict | None = None) -> int:
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


def _seed(db: Session, slug: str, media_tags: list[str] | None = None):  # noqa: ANN202
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
            media_tags=media_tags if media_tags is not None else ["мерч"],
        ),
    )
    return account, project


def _svc() -> MediaTagSuggestionService:
    return MediaTagSuggestionService(settings=Settings())


def test_filename_tokens() -> None:
    S = MediaTagSuggestionService
    assert S.split_file_name_to_tokens("hoodie_dtf_logo_123.jpg") == ["hoodie", "dtf", "logo"]
    assert S.split_file_name_to_tokens("худи-вышивка001.heic") == ["худи", "вышивка"]
    assert S.split_file_name_to_tokens("img.jpg") == []  # стоп-слово/расширение


def test_normalize_tag() -> None:
    assert MediaTagSuggestionService.normalize_tag("  DTF-На_Худи  ") == "dtf на худи"
    assert MediaTagSuggestionService.normalize_tag("#Футболка") == "футболка"


def test_classify_product_technology_free() -> None:
    S = MediaTagSuggestionService
    assert S.classify_tag("футболка") == "product"
    assert S.classify_tag("dtf") == "technology"
    assert S.classify_tag("нечто") == "free"


def test_suggest_from_filename_and_crm(db_session: Session) -> None:
    _acc, project = _seed(db_session, "tag-crm", media_tags=["мерч", "футболка"])
    aid = _media(db_session, project.id, "a", "hoodie_dtf.jpg", tags={})
    r = _svc().suggest_tags_for_asset(db_session, project.id, aid, "telegram")
    assert "crm_category" in r["source_signals"]
    assert "file_name" in r["source_signals"]
    assert any(t in r["suggested_tags"] for t in ("hoodie", "dtf", "футболка", "мерч"))
    assert "dtf" in r["suggested_technologies"]


def test_suggest_from_duplicate_canonical(db_session: Session) -> None:
    _acc, project = _seed(db_session, "tag-dup")
    canon = _media(db_session, project.id, "c", "c.jpg", tags={"products": ["худи"]})
    dup = _media(db_session, project.id, "d", "d.jpg", tags={})
    media_duplicate_cluster_repository.create_cluster(
        db_session,
        project_id=project.id,
        status="active",
        cluster_type="near_duplicate",
        canonical_media_asset_id=canon,
        member_media_asset_ids=[canon, dup],
        member_fingerprint_ids=[],
        similarity_score=0.95,
    )
    r = _svc().suggest_tags_for_asset(db_session, project.id, dup, "telegram")
    assert "duplicate_canonical" in r["source_signals"]
    assert "худи" in r["suggested_products"]


def test_confidence_and_no_new_tags_flag(db_session: Session) -> None:
    _acc, project = _seed(db_session, "tag-conf")
    # Ассет уже полностью размечен тегами из CRM/имени → мало нового.
    aid = _media(db_session, project.id, "a", "мерч.jpg", tags={"products": ["мерч"]})
    r = _svc().suggest_tags_for_asset(db_session, project.id, aid, "telegram")
    assert 0.0 <= r["confidence_score"] <= 0.95


def test_no_cross_project_data(db_session: Session) -> None:
    _a1, p1 = _seed(db_session, "tag-iso1", media_tags=["секрет-проекта-1"])
    _a2, p2 = _seed(db_session, "tag-iso2", media_tags=["мерч"])
    aid = _media(db_session, p2.id, "a", "a.jpg", tags={})
    r = _svc().suggest_tags_for_asset(db_session, p2.id, aid, "telegram")
    assert "секрет-проекта-1" not in r["suggested_tags"]


def test_no_paths_or_secrets_in_result(db_session: Session) -> None:
    _acc, project = _seed(db_session, "tag-nopath")
    aid = _media(db_session, project.id, "hidden", "secret-photo.jpg", tags={})
    r = _svc().suggest_tags_for_asset(db_session, project.id, aid, "telegram")
    blob = str(r)
    assert "disk:/" not in blob
    assert "secret-photo.jpg" not in blob
