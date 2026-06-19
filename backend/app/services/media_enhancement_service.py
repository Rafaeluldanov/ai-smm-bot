"""Сервис улучшения медиа (Media Enhancement).

Создаёт УЛУЧШЕННЫЕ КОПИИ изображений (``MediaAssetVariant``), не трогая оригинал
``MediaAsset``. Видео пропускаются. Спорные правки (меняющие цвет/текстуру
изделия) помечаются статусом ``needs_review``.

Поток (``enhance_media_asset``):
    1) найти медиа-актив; 2) пропустить видео; 3) если уже есть enhanced и не
    force — конфликт/пропуск; 4) скачать байты (MediaDownloadService);
    5) прогнать ImageEnhancementProcessor; 6) сохранить копию в STORAGE_DIR;
    7) создать MediaAssetVariant; 8) при предупреждениях — needs_review.

Оригинальный ``MediaAsset`` НЕ изменяется (ни путь, ни статус, ни файл).
"""

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.media_asset import MediaAsset
from app.models.project import Project
from app.repositories import media_asset_repository, project_repository
from app.repositories import media_asset_variant_repository as variant_repo
from app.repositories.media_asset_repository import MediaAssetNotFoundError
from app.schemas.media_enhancement import (
    MediaAssetVariantCreate,
    MediaAssetVariantRead,
    MediaEnhancementRequest,
    MediaEnhancementResult,
    MediaEnhancementSummary,
    ProjectMediaEnhancementRequest,
    ProjectMediaEnhancementResult,
)
from app.services.image_enhancement_processor import (
    ImageEnhancementError,
    ImageEnhancementProcessor,
)
from app.services.media_download_service import MediaDownloadError, SupportsMediaDownload
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

logger = get_logger(__name__)

# Видео не улучшаем на этом этапе (только изображения).
_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".m2ts"})


class VariantAlreadyExistsError(Exception):
    """У медиа-актива уже есть улучшенный вариант (нужен force для пересоздания)."""

    def __init__(self, media_asset_id: int, variant_id: int) -> None:
        self.media_asset_id = media_asset_id
        self.variant_id = variant_id
        super().__init__(
            f"Для медиа id={media_asset_id} уже есть улучшенный вариант "
            f"(id={variant_id}); передайте force=true для пересоздания"
        )


class MediaEnhancementService:
    """Оркестрирует скачивание, обработку и сохранение улучшенных копий медиа."""

    def __init__(
        self,
        processor: ImageEnhancementProcessor,
        downloader: SupportsMediaDownload,
        *,
        storage_dir: str,
        default_profile: str = "social_safe",
    ) -> None:
        self._processor = processor
        self._downloader = downloader
        self._storage_dir = storage_dir
        self._default_profile = default_profile

    # --- Публичные методы ---

    def enhance_media_asset(
        self, db: Session, media_asset_id: int, request: MediaEnhancementRequest
    ) -> MediaEnhancementResult:
        """Улучшить один медиа-актив (создать производную копию). Оригинал не меняется."""
        media = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if media is None:
            raise MediaAssetNotFoundError(media_asset_id)

        if self._is_video(media.file_name):
            return MediaEnhancementResult(
                media_asset_id=media.id,
                variant=None,
                status="skipped_video",
                warnings=["Видео не улучшается на этом этапе (только изображения)"],
                operations_applied=[],
            )

        profile = request.profile or self._default_profile
        latest = variant_repo.get_latest_variant_for_media(db, media.id, "enhanced")
        if request.save and latest is not None and not request.force:
            raise VariantAlreadyExistsError(media.id, latest.id)

        downloaded = self._downloader.download_media_asset(db, media)
        enhanced = self._processor.enhance_image_bytes(
            downloaded.bytes, profile, request.operations
        )

        status = "needs_review" if enhanced.warnings else "created"

        if not request.save:
            # Превью без сохранения: запись и файл не создаём.
            return MediaEnhancementResult(
                media_asset_id=media.id,
                variant=None,
                status="preview",
                warnings=list(enhanced.warnings),
                operations_applied=list(enhanced.operations_applied),
            )

        output_path = self._save_output(
            db, media, enhanced.output_bytes, profile, enhanced.output_format
        )
        variant = variant_repo.create_variant(
            db,
            MediaAssetVariantCreate(
                media_asset_id=media.id,
                project_id=media.project_id,
                variant_type="enhanced",
                status=status,
                source_media_asset_id=media.id,
                source_path=media.yandex_disk_path,
                output_path=output_path,
                output_format=enhanced.output_format,
                width=enhanced.width,
                height=enhanced.height,
                file_size=enhanced.file_size,
                operations=list(enhanced.operations_applied),
                before_metadata=dict(enhanced.before_metadata),
                after_metadata=dict(enhanced.after_metadata),
                quality_score=enhanced.quality_score,
                warnings=list(enhanced.warnings),
                error_message=None,
            ),
        )
        logger.info(
            "Улучшено медиа id=%s -> вариант id=%s (%s), операции=%s",
            media.id,
            variant.id,
            variant.status,
            enhanced.operations_applied,
        )
        return MediaEnhancementResult(
            media_asset_id=media.id,
            variant=MediaAssetVariantRead.model_validate(variant),
            status=variant.status,
            warnings=list(enhanced.warnings),
            operations_applied=list(enhanced.operations_applied),
        )

    def enhance_project_media(
        self, db: Session, request: ProjectMediaEnhancementRequest
    ) -> ProjectMediaEnhancementResult:
        """Пакетно улучшить медиа проекта (по статусу/лимиту)."""
        project = self._resolve_project(db, request)
        medias = media_asset_repository.list_media_assets(
            db, project_id=project.id, status=request.status, limit=request.limit
        )
        result = ProjectMediaEnhancementResult(
            project_id=project.id,
            project_slug=project.slug,
            profile=request.profile,
            total_candidates=len(medias),
        )
        for media in medias:
            item_request = MediaEnhancementRequest(
                profile=request.profile, force=request.force, save=True, operations=None
            )
            try:
                item = self.enhance_media_asset(db, media.id, item_request)
            except VariantAlreadyExistsError:
                result.skipped += 1
                continue
            except (MediaDownloadError, ImageEnhancementError) as exc:
                result.failed += 1
                result.errors.append(f"media id={media.id}: {exc}")
                continue

            if item.status == "skipped_video":
                result.skipped += 1
            elif item.status == "needs_review":
                result.enhanced += 1
                result.needs_review += 1
            elif item.status == "created":
                result.enhanced += 1
            result.results.append(item)

        logger.info(
            "Пакетное улучшение %s: кандидатов=%d, улучшено=%d, review=%d, пропущено=%d, ошибок=%d",
            project.slug,
            result.total_candidates,
            result.enhanced,
            result.needs_review,
            result.skipped,
            result.failed,
        )
        return result

    def get_enhancement_summary(
        self, db: Session, project_id: int | None = None
    ) -> MediaEnhancementSummary:
        """Сводка по производным вариантам (по статусам и типам)."""
        total, by_status, by_type = variant_repo.summarize_variants(db, project_id)
        return MediaEnhancementSummary(
            project_id=project_id,
            total_variants=total,
            by_status=by_status,
            by_variant_type=by_type,
        )

    # --- Внутреннее ---

    def _resolve_project(self, db: Session, request: ProjectMediaEnhancementRequest) -> Project:
        if request.project_id is not None:
            project = project_repository.get_project_by_id(db, request.project_id)
            if project is None:
                raise ProjectNotFoundError(request.project_id)
            return project
        if request.project_slug:
            project = project_repository.get_project_by_slug(db, request.project_slug)
            if project is None:
                raise ProjectNotFoundError(request.project_slug)
            return project
        raise ProjectNotFoundError("требуется project_id или project_slug")

    def _save_output(
        self,
        db: Session,
        media: MediaAsset,
        output_bytes: bytes,
        profile: str,
        output_format: str,
    ) -> str:
        storage = Path(self._storage_dir)
        storage.mkdir(parents=True, exist_ok=True)
        existing = variant_repo.list_variants(
            db, media_asset_id=media.id, variant_type="enhanced", limit=10_000
        )
        seq = len(existing) + 1
        base_name = self._processor.build_output_file_name(
            media.id, media.file_name, profile, output_format
        )
        target = storage / f"{seq:03d}_{base_name}"
        target.write_bytes(output_bytes)
        return str(target)

    @staticmethod
    def _is_video(file_name: str) -> bool:
        lowered = file_name.lower()
        return any(lowered.endswith(ext) for ext in _VIDEO_EXTENSIONS)
