"""Тесты подбора собственного медиа под SEO-посты (Задача 7)."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import media_asset_repository as media_repo
from app.repositories import media_asset_variant_repository as variant_repo
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.media_enhancement import MediaAssetVariantCreate
from app.schemas.project import ProjectCreate
from app.services.project_media_paths import is_public_path_allowed_for_project
from app.services.seo_media_selection_service import SeoMediaSelectionService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def _project(db: Session, slug: str = "teeon") -> int:
    return create_project(db, ProjectCreate(name=slug, slug=slug)).id


def _own_media(db: Session, project_id: int, name: str, tags: dict) -> int:  # noqa: ANN001
    return media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=name,
            yandex_disk_path=f"disk:/{name}",
            source_type="internal",
            license_type="company_owned",
            status="approved",
            tags=tags,
        ),
    ).id


def test_selects_own_media_by_product(db_session: Session) -> None:
    project_id = _project(db_session)
    _own_media(db_session, project_id, "f.jpg", {"products": ["футболка"]})

    candidates = SeoMediaSelectionService().select_media(db_session, "teeon", products=["футболки"])
    assert len(candidates) == 1
    assert candidates[0].source_type == "internal"
    assert candidates[0].media_source == "original"
    assert candidates[0].preferred_media_path is None


def test_excludes_external_stock_and_needs_review(db_session: Session) -> None:
    project_id = _project(db_session)
    _own_media(db_session, project_id, "own.jpg", {"products": ["худи"]})
    media_repo.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project_id,
            file_name="stock.jpg",
            yandex_disk_path="disk:/stock.jpg",
            source_type="external_stock",
            license_type="commercial_use_required",
            status="approved",
            tags={"products": ["худи"]},
        ),
    )
    candidates = SeoMediaSelectionService().select_media(db_session, "teeon", products=["худи"])
    files = {c.file_name for c in candidates}
    assert files == {"own.jpg"}  # внешний сток не берём


def test_prefers_non_reference_when_own_exists(db_session: Session) -> None:
    project_id = _project(db_session)
    _own_media(db_session, project_id, "clean.jpg", {"products": ["кепка"]})
    _own_media(
        db_session,
        project_id,
        "ref.jpg",
        {"products": ["кепка"], "categories": ["external_reference"]},
    )
    candidates = SeoMediaSelectionService().select_media(db_session, "teeon", products=["кепки"])
    files = {c.file_name for c in candidates}
    assert files == {"clean.jpg"}


def test_returns_preferred_media_path_for_enhanced_variant(db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _own_media(db_session, project_id, "orig.jpg", {"technologies": ["dtf"]})
    variant_repo.create_variant(
        db_session,
        MediaAssetVariantCreate(
            media_asset_id=asset_id,
            project_id=project_id,
            variant_type="enhanced",
            status="approved",
            output_path="/enhanced/orig_enhanced.jpg",
        ),
    )
    best = SeoMediaSelectionService().select_best(db_session, "teeon", technologies=["DTF-печать"])
    assert best is not None
    assert best.media_source == "enhanced_variant"
    assert best.preferred_media_path == "/enhanced/orig_enhanced.jpg"


def test_unknown_project_raises(db_session: Session) -> None:
    with pytest.raises(ProjectNotFoundError):
        SeoMediaSelectionService().select_media(db_session, "no-such-project")


# --- Изоляция медиа между проектами (папки Яндекс Диска) ---


def test_teeon_cannot_use_fabrica_media() -> None:
    assert is_public_path_allowed_for_project("teeon", "/fabrica suvenirov/IMG.HEIC") is False
    assert is_public_path_allowed_for_project("teeon", "/SMM/Тион/Фабрика сувениров/x.jpg") is False


def test_fabric_can_use_teeon_and_fabrica_media() -> None:
    assert is_public_path_allowed_for_project("fabric-souvenirs", "/SMM/Тион/x.jpg") is True
    assert (
        is_public_path_allowed_for_project("fabric-souvenirs", "/fabrica suvenirov/x.jpg") is True
    )
