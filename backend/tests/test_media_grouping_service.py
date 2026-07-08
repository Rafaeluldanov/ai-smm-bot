"""Тесты сервиса группировки медиа (v0.1.14) — offline, SQLite.

Проверяют: группировку по продуктам/технологиям, строгий отбор собственных
approved-медиа, обработку видео (в группе, но не загружается) и сборку поста с
SEO-ссылкой и generation_notes.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.repositories import media_asset_repository, media_asset_variant_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.media_enhancement import MediaAssetVariantCreate
from app.schemas.project import ProjectCreate
from app.services.media_grouping_service import MediaGroupingService


def _project(db: Session, slug: str = "teeon") -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug=slug)).id


def _asset(
    db: Session,
    project_id: int,
    file_name: str,
    tags: dict[str, Any],
    *,
    status: str = "approved",
    source_type: str = "internal",
    license_type: str | None = "company_owned",
) -> int:
    return media_asset_repository.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=file_name,
            yandex_disk_path=f"public://yandex/teeon/teeon/{file_name}",
            source_type=source_type,
            license_type=license_type,
            status=status,
            tags=tags,
        ),
    ).id


def _ids(groups: list[Any]) -> list[int]:
    return [media_id for group in groups for media_id in group.media_asset_ids]


# --------------------------------------------------------------------------- #
# Группировка                                                                  #
# --------------------------------------------------------------------------- #


def test_groups_tshirts_by_products(db_session: Session) -> None:
    project_id = _project(db_session)
    a1 = _asset(db_session, project_id, "tshirt_1.jpg", {"products": ["футболка"]})
    a2 = _asset(db_session, project_id, "tshirt_2.jpg", {"products": ["футболка"]})

    groups = MediaGroupingService().group_project_media(db_session, "teeon")

    tshirt = [g for g in groups if g.group_key == "футболка"]
    assert len(tshirt) == 1
    group = tshirt[0]
    assert group.group_type == "product"
    assert set(group.media_asset_ids) == {a1, a2}
    assert group.image_count == 2
    assert group.video_count == 0
    assert "футболка" in group.matched_tags


def test_groups_dtf_and_silk_by_technologies(db_session: Session) -> None:
    project_id = _project(db_session)
    d1 = _asset(db_session, project_id, "dtf_1.jpg", {"technologies": ["dtf"]})
    d2 = _asset(db_session, project_id, "dtf_2.jpg", {"technologies": ["dtf"]})
    silk = _asset(db_session, project_id, "silk_1.jpg", {"technologies": ["шелкография"]})

    groups = MediaGroupingService().group_project_media(db_session, "teeon")
    by_key = {group.group_key: group for group in groups}

    assert "dtf" in by_key
    assert by_key["dtf"].group_type == "technology"
    assert set(by_key["dtf"].media_asset_ids) == {d1, d2}
    assert "шелкография" in by_key
    assert by_key["шелкография"].group_type == "technology"
    assert by_key["шелкография"].media_asset_ids == [silk]


# --------------------------------------------------------------------------- #
# Строгий отбор собственных approved-медиа                                     #
# --------------------------------------------------------------------------- #


def test_excludes_external_reference_and_external_stock(db_session: Session) -> None:
    project_id = _project(db_session)
    own = _asset(db_session, project_id, "own_tshirt.jpg", {"products": ["футболка"]})
    _asset(
        db_session,
        project_id,
        "ref.jpg",
        {"products": ["футболка"], "categories": ["external_reference"]},
    )
    _asset(
        db_session,
        project_id,
        "stock.jpg",
        {"products": ["футболка"]},
        source_type="external_stock",
    )

    groups = MediaGroupingService().group_project_media(db_session, "teeon")
    assert _ids(groups) == [own]


def test_excludes_non_approved_statuses(db_session: Session) -> None:
    project_id = _project(db_session)
    good = _asset(db_session, project_id, "ok.jpg", {"products": ["футболка"]})
    _asset(db_session, project_id, "new.jpg", {"products": ["футболка"]}, status="new")
    _asset(db_session, project_id, "rejected.jpg", {"products": ["футболка"]}, status="rejected")
    _asset(
        db_session,
        project_id,
        "reshoot.jpg",
        {"products": ["футболка"]},
        status="needs_reshoot",
    )
    _asset(
        db_session,
        project_id,
        "license.jpg",
        {"products": ["футболка"]},
        status="needs_license_review",
    )

    groups = MediaGroupingService().group_project_media(db_session, "teeon")
    assert _ids(groups) == [good]


def test_only_company_owned_internal(db_session: Session) -> None:
    project_id = _project(db_session)
    good = _asset(db_session, project_id, "own.jpg", {"products": ["футболка"]})
    _asset(
        db_session,
        project_id,
        "ext_license.jpg",
        {"products": ["футболка"]},
        license_type="external_needs_review",
    )
    _asset(
        db_session,
        project_id,
        "upload.jpg",
        {"products": ["футболка"]},
        source_type="upload",
    )

    groups = MediaGroupingService().group_project_media(db_session, "teeon")
    assert _ids(groups) == [good]


# --------------------------------------------------------------------------- #
# Enhanced-вариант и видео                                                     #
# --------------------------------------------------------------------------- #


def test_uses_approved_enhanced_variant_as_media_path(db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, "orig.HEIC", {"products": ["футболка"]})
    media_asset_variant_repository.create_variant(
        db_session,
        MediaAssetVariantCreate(
            media_asset_id=asset_id,
            project_id=project_id,
            variant_type="enhanced",
            status="approved",
            output_path="backend/data/enhanced_media/e.jpg",
        ),
    )
    service = MediaGroupingService()

    groups = service.group_project_media(db_session, "teeon", tag="футболка")
    draft = service.build_post_draft_from_group(db_session, "teeon", groups[0])

    media_files = draft.generation_notes["media_files"]
    entry = next(item for item in media_files if item["id"] == asset_id)
    assert entry["media_path"] == "backend/data/enhanced_media/e.jpg"
    assert entry["media_source"] == "enhanced_variant"
    assert entry["media_kind"] == "image"


def test_video_in_group_marked_not_uploadable(db_session: Session) -> None:
    project_id = _project(db_session)
    image_id = _asset(db_session, project_id, "tshirt.jpg", {"products": ["футболка"]})
    video_id = _asset(
        db_session,
        project_id,
        "tshirt_clip.MOV",
        {"products": ["футболка"]},
        status="approved_video",
    )
    service = MediaGroupingService()

    groups = service.group_project_media(db_session, "teeon", tag="футболка")
    group = groups[0]
    assert image_id in group.media_asset_ids
    assert video_id in group.media_asset_ids
    assert group.image_count == 1
    assert group.video_count == 1
    assert any("видео" in warning.lower() for warning in group.warnings)

    draft = service.build_post_draft_from_group(db_session, "teeon", group)
    notes = draft.generation_notes
    assert notes["selected_for_vk_upload"] is True
    assert notes["video_count"] == 1
    # Главное медиа для VK — фото, а не видео.
    assert draft.primary_media_asset_id == image_id


def test_video_only_group_not_selected_for_vk(db_session: Session) -> None:
    project_id = _project(db_session)
    _asset(
        db_session,
        project_id,
        "clip.MOV",
        {"products": ["футболка"]},
        status="approved_video",
    )
    service = MediaGroupingService()

    groups = service.group_project_media(db_session, "teeon", tag="футболка")
    draft = service.build_post_draft_from_group(db_session, "teeon", groups[0])
    assert draft.generation_notes["selected_for_vk_upload"] is False
    assert draft.generation_notes["image_count"] == 0


# --------------------------------------------------------------------------- #
# Фильтр по тегу и создание поста                                              #
# --------------------------------------------------------------------------- #


def test_tag_filter_selects_only_matching(db_session: Session) -> None:
    project_id = _project(db_session)
    tshirt = _asset(db_session, project_id, "tshirt.jpg", {"products": ["футболка"]})
    hoodie = _asset(db_session, project_id, "hoodie.jpg", {"products": ["худи"]})

    groups = MediaGroupingService().group_project_media(db_session, "teeon", tag="футболка")
    ids = _ids(groups)
    assert tshirt in ids
    assert hoodie not in ids


def test_create_post_from_group_needs_review_with_notes_and_link(db_session: Session) -> None:
    project_id = _project(db_session)
    a1 = _asset(db_session, project_id, "tshirt_1.jpg", {"products": ["футболка"]})
    a2 = _asset(db_session, project_id, "tshirt_2.jpg", {"products": ["футболка"]})
    service = MediaGroupingService()

    groups = service.group_project_media(db_session, "teeon", tag="футболка")
    post = service.create_post_from_media_group(db_session, "teeon", groups[0])

    assert post.status == "needs_review"
    assert post.media_asset_id in {a1, a2}
    assert set(post.generation_notes["media_asset_ids"]) == {a1, a2}
    assert post.generation_notes["media_count"] == 2
    assert post.generation_notes["image_count"] == 2
    # SEO-ссылка на сайт присутствует в тексте.
    assert "Подробнее и расчёт тиража" in (post.vk_text or "")
