"""CLI конвертации внешнего кандидата в MediaAsset (без сети).

Запуск:
  make convert-external-image candidate_id=1
  python -m app.scripts.convert_external_image --candidate-id 1 --status needs_license_review
"""

import argparse

from app.api.deps import (
    get_external_image_provider_registry,
    get_external_image_search_service,
)
from app.db.session import get_sessionmaker
from app.repositories.external_image_repository import ExternalImageCandidateNotFoundError
from app.schemas.external_image import ExternalImageConvertRequest
from app.services.external_image_search_service import ExternalImageConversionError


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов конвертации."""
    parser = argparse.ArgumentParser(description="Конвертация внешнего кандидата в MediaAsset")
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--status", default="needs_license_review")
    return parser


def main() -> None:
    """Точка входа CLI конвертации."""
    args = build_parser().parse_args()
    request = ExternalImageConvertRequest(status=args.status)

    service = get_external_image_search_service(get_external_image_provider_registry())
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.convert_candidate_to_media_asset(db, args.candidate_id, request)
        except ExternalImageCandidateNotFoundError as exc:
            print(f"Ошибка: {exc}")
            return
        except ExternalImageConversionError as exc:
            print(f"Нельзя конвертировать: {exc}")
            return

    print(
        f"Кандидат {result.candidate.id} → MediaAsset id={result.media_asset_id} "
        f"(статус кандидата: {result.candidate.review_status})"
    )
    for warning in result.warnings:
        print(f"  ! {warning}")


if __name__ == "__main__":
    main()
