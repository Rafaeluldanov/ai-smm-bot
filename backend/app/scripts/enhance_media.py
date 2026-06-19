"""Улучшить один медиа-актив (создать производную копию).

Запуск:
  make enhance-media media_asset_id=1
  python -m app.scripts.enhance_media --media-asset-id 1 --profile social_safe

Создаёт улучшенную КОПИЮ (MediaAssetVariant); оригинал не меняется. Не входит
в make check. Для публичного источника нужен YANDEX_DISK_PUBLIC_SMM_URL.
"""

import argparse

from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.integrations.yandex_disk.client import YandexDiskPublicClient
from app.repositories.media_asset_repository import MediaAssetNotFoundError
from app.schemas.media_enhancement import MediaEnhancementRequest, MediaEnhancementResult
from app.services.image_enhancement_processor import (
    ImageEnhancementError,
    ImageEnhancementProcessor,
)
from app.services.media_download_service import MediaDownloadError, MediaDownloadService
from app.services.media_enhancement_service import (
    MediaEnhancementService,
    VariantAlreadyExistsError,
)


def build_enhancement_service(settings: Settings) -> MediaEnhancementService:
    """Собрать сервис улучшения медиа из настроек (Pillow + публичный загрузчик)."""
    processor = ImageEnhancementProcessor(
        output_format=settings.media_enhancement_output_format,
        jpeg_quality=settings.media_enhancement_jpeg_quality,
        max_image_mb=settings.media_enhancement_max_image_mb,
    )
    downloader = MediaDownloadService(
        public_client=YandexDiskPublicClient(base_url=settings.yandex_disk_base_url),
        public_key=settings.yandex_disk_public_smm_url or None,
    )
    return MediaEnhancementService(
        processor=processor,
        downloader=downloader,
        storage_dir=settings.media_enhancement_storage_dir,
        default_profile=settings.media_enhancement_default_profile,
    )


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов улучшения одного медиа."""
    parser = argparse.ArgumentParser(description="Улучшить медиа-актив (создать копию)")
    parser.add_argument("--media-asset-id", type=int, required=True, help="id медиа-актива")
    parser.add_argument("--profile", default=None, help="social_safe | product_clean | minimal")
    parser.add_argument("--force", action="store_true", help="пересоздать, даже если уже улучшено")
    parser.add_argument("--no-save", action="store_true", help="превью без сохранения копии")
    return parser


def _print_result(result: MediaEnhancementResult) -> None:
    print(f"Медиа id: {result.media_asset_id}")
    print(f"Статус:   {result.status}")
    print(f"Операции: {', '.join(result.operations_applied) or '—'}")
    if result.variant is not None:
        v = result.variant
        print(f"Вариант id: {v.id} ({v.variant_type}, {v.status})")
        print(f"Файл:       {v.output_path}")
        print(f"Размер:     {v.width}x{v.height}, {v.file_size} байт, качество {v.quality_score}")
    if result.warnings:
        print("Предупреждения:")
        for warning in result.warnings:
            print(f"  ! {warning}")


def main() -> None:
    """Точка входа CLI улучшения одного медиа."""
    args = build_parser().parse_args()
    settings = get_settings()
    profile = args.profile or settings.media_enhancement_default_profile
    request = MediaEnhancementRequest(profile=profile, force=args.force, save=not args.no_save)

    service = build_enhancement_service(settings)
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.enhance_media_asset(db, args.media_asset_id, request)
        except MediaAssetNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return
        except VariantAlreadyExistsError as exc:
            print(f"Пропуск: {exc}")
            return
        except (MediaDownloadError, ImageEnhancementError) as exc:
            print(f"Ошибка обработки: {exc}")
            return
        _print_result(result)


if __name__ == "__main__":
    main()
