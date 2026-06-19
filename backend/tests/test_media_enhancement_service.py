"""Тесты сервиса улучшения медиа (fake-загрузчик + Pillow, без сети/AI)."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.repositories import media_asset_variant_repository as vrepo
from app.repositories.media_asset_repository import create_media_asset, get_media_asset_by_id
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.media_enhancement import (
    MediaEnhancementRequest,
    ProjectMediaEnhancementRequest,
)
from app.schemas.project import ProjectCreate
from app.services.image_enhancement_processor import ImageEnhancementProcessor
from app.services.media_download_service import DownloadedMedia
from app.services.media_enhancement_service import (
    MediaEnhancementService,
    VariantAlreadyExistsError,
)


def _png(width: int = 1200, height: int = 800) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (120, 90, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeDownloader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls = 0

    def download_media_asset(self, db: Session, media_asset: MediaAsset) -> DownloadedMedia:
        self.calls += 1
        return DownloadedMedia(
            file_name=media_asset.file_name,
            content_type="image/png",
            bytes=self.data,
            source_url="fake://x",
        )


def _service(tmp_path: Path, profile: str = "social_safe") -> MediaEnhancementService:
    return MediaEnhancementService(
        processor=ImageEnhancementProcessor(),
        downloader=_FakeDownloader(_png()),
        storage_dir=str(tmp_path),
        default_profile=profile,
    )


def _seed_media(db: Session, file_name: str = "a.jpg", status: str = "approved") -> tuple[int, int]:
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    media = create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project.id,
            file_name=file_name,
            yandex_disk_path=f"public://yandex/teeon/SMM/Тион/{file_name}",
            status=status,
        ),
    )
    return project.id, media.id


def test_enhance_creates_variant_without_touching_original(
    db_session: Session, tmp_path: Path
) -> None:
    _project_id, media_id = _seed_media(db_session)
    service = _service(tmp_path)

    result = service.enhance_media_asset(
        db_session, media_id, MediaEnhancementRequest(profile="social_safe")
    )

    assert result.status == "created"
    assert result.variant is not None
    assert result.variant.output_path is not None
    assert Path(result.variant.output_path).exists()

    # Оригинал не изменился: ни статус, ни путь.
    original = get_media_asset_by_id(db_session, media_id)
    assert original is not None
    assert original.status == "approved"
    assert original.yandex_disk_path == "public://yandex/teeon/SMM/Тион/a.jpg"


def test_force_false_blocks_duplicate(db_session: Session, tmp_path: Path) -> None:
    _project_id, media_id = _seed_media(db_session)
    service = _service(tmp_path)
    service.enhance_media_asset(db_session, media_id, MediaEnhancementRequest())

    with pytest.raises(VariantAlreadyExistsError):
        service.enhance_media_asset(db_session, media_id, MediaEnhancementRequest(force=False))


def test_force_true_creates_second_variant(db_session: Session, tmp_path: Path) -> None:
    _project_id, media_id = _seed_media(db_session)
    service = _service(tmp_path)
    service.enhance_media_asset(db_session, media_id, MediaEnhancementRequest())
    service.enhance_media_asset(db_session, media_id, MediaEnhancementRequest(force=True))

    variants = vrepo.list_variants(db_session, media_asset_id=media_id)
    assert len(variants) == 2


def test_video_skipped(db_session: Session, tmp_path: Path) -> None:
    _project_id, media_id = _seed_media(db_session, file_name="clip.mp4")
    service = _service(tmp_path)

    result = service.enhance_media_asset(db_session, media_id, MediaEnhancementRequest())

    assert result.status == "skipped_video"
    assert result.variant is None
    assert vrepo.list_variants(db_session, media_asset_id=media_id) == []


def test_warnings_lead_to_needs_review(db_session: Session, tmp_path: Path) -> None:
    _project_id, media_id = _seed_media(db_session)
    service = _service(tmp_path)

    result = service.enhance_media_asset(
        db_session, media_id, MediaEnhancementRequest(profile="product_clean")
    )

    assert result.status == "needs_review"
    assert result.warnings
    assert result.variant is not None
    assert result.variant.status == "needs_review"


def test_preview_without_save_creates_no_row(db_session: Session, tmp_path: Path) -> None:
    _project_id, media_id = _seed_media(db_session)
    service = _service(tmp_path)

    result = service.enhance_media_asset(db_session, media_id, MediaEnhancementRequest(save=False))

    assert result.status == "preview"
    assert result.variant is None
    assert vrepo.list_variants(db_session, media_asset_id=media_id) == []


def test_project_batch_enhancement(db_session: Session, tmp_path: Path) -> None:
    project = create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    for i in range(3):
        create_media_asset(
            db_session,
            MediaAssetCreate(
                project_id=project.id,
                file_name=f"a{i}.jpg",
                yandex_disk_path=f"public://yandex/teeon/SMM/Тион/a{i}.jpg",
                status="approved",
            ),
        )
    create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=project.id,
            file_name="v.mp4",
            yandex_disk_path="public://yandex/teeon/SMM/Тион/v.mp4",
            status="approved",
        ),
    )
    service = _service(tmp_path)

    result = service.enhance_project_media(
        db_session,
        ProjectMediaEnhancementRequest(
            project_slug="teeon", status="approved", profile="social_safe"
        ),
    )

    assert result.total_candidates == 4
    assert result.enhanced == 3
    assert result.skipped == 1  # видео
    assert result.failed == 0
