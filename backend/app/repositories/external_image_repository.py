"""Репозиторий внешних изображений-кандидатов (ExternalImageCandidate).

Бизнес-уникальность — пара (provider, source_url): upsert по ней не плодит один
и тот же внешний источник. Уже отревьюенные (approved/rejected/converted)
кандидаты повторный upsell не сбрасывает без явного review.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.external_image_candidate import ExternalImageCandidate
from app.schemas.external_image import (
    ExternalImageCandidateCreate,
    ExternalImageCandidateUpdate,
)

# Допустимые статусы review.
ALLOWED_REVIEW_STATUSES: list[str] = [
    "candidate",
    "needs_review",
    "approved",
    "rejected",
    "converted_to_media_asset",
]

# Статусы, которые upsert не перезаписывает (требуют явного review).
_PROTECTED_REVIEW_STATUSES: set[str] = {"approved", "rejected", "converted_to_media_asset"}

# Поля метаданных, обновляемые при upsert существующего кандидата.
_UPSERT_FIELDS: tuple[str, ...] = (
    "query",
    "topic_id",
    "post_id",
    "preview_url",
    "download_url",
    "title",
    "description",
    "author_name",
    "author_url",
    "license_name",
    "license_url",
    "commercial_use_allowed",
    "modification_allowed",
    "attribution_required",
    "contains_people",
    "contains_logo",
    "safe_for_business",
    "forbidden_usage",
    "tags",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ExternalImageCandidateNotFoundError(Exception):
    """Кандидат внешнего изображения не найден."""

    def __init__(self, candidate_id: int) -> None:
        self.candidate_id = candidate_id
        super().__init__(f"Кандидат внешнего изображения id={candidate_id} не найден")


class InvalidExternalImageReviewStatusError(Exception):
    """Передан неизвестный статус review."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"Неизвестный статус review: '{status}'")


def get_candidate_by_id(db: Session, candidate_id: int) -> ExternalImageCandidate | None:
    """Вернуть кандидата по id или None."""
    return db.get(ExternalImageCandidate, candidate_id)


def get_candidate_by_provider_source(
    db: Session, provider: str, source_url: str
) -> ExternalImageCandidate | None:
    """Вернуть кандидата по (provider, source_url) или None."""
    stmt = select(ExternalImageCandidate).where(
        ExternalImageCandidate.provider == provider,
        ExternalImageCandidate.source_url == source_url,
    )
    return db.scalars(stmt).first()


def list_candidates(
    db: Session,
    project_id: int | None = None,
    topic_id: int | None = None,
    post_id: int | None = None,
    provider: str | None = None,
    review_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ExternalImageCandidate]:
    """Вернуть кандидатов с фильтрами и пагинацией."""
    stmt = select(ExternalImageCandidate).order_by(ExternalImageCandidate.id)
    if project_id is not None:
        stmt = stmt.where(ExternalImageCandidate.project_id == project_id)
    if topic_id is not None:
        stmt = stmt.where(ExternalImageCandidate.topic_id == topic_id)
    if post_id is not None:
        stmt = stmt.where(ExternalImageCandidate.post_id == post_id)
    if provider is not None:
        stmt = stmt.where(ExternalImageCandidate.provider == provider)
    if review_status is not None:
        stmt = stmt.where(ExternalImageCandidate.review_status == review_status)
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def create_candidate(db: Session, data: ExternalImageCandidateCreate) -> ExternalImageCandidate:
    """Создать кандидата."""
    candidate = ExternalImageCandidate(**data.model_dump())
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def update_candidate(
    db: Session, candidate: ExternalImageCandidate, data: ExternalImageCandidateUpdate
) -> ExternalImageCandidate:
    """Частично обновить кандидата (только переданные поля)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(candidate, field, value)
    db.commit()
    db.refresh(candidate)
    return candidate


def upsert_candidate(
    db: Session, data: ExternalImageCandidateCreate
) -> tuple[ExternalImageCandidate, str]:
    """Создать или обновить кандидата по (provider, source_url).

    Возвращает ``(candidate, action)``, где ``action`` ∈ {created, updated,
    unchanged}. Защищённые review-статусы (approved/rejected/converted) не
    перезаписываются.
    """
    existing = get_candidate_by_provider_source(db, data.provider, data.source_url)
    if existing is None:
        return create_candidate(db, data), "created"

    changed = False
    for field in _UPSERT_FIELDS:
        new_value = getattr(data, field)
        if getattr(existing, field) != new_value:
            setattr(existing, field, new_value)
            changed = True

    if (
        existing.review_status not in _PROTECTED_REVIEW_STATUSES
        and existing.review_status != data.review_status
    ):
        existing.review_status = data.review_status
        changed = True

    if not changed:
        return existing, "unchanged"

    db.commit()
    db.refresh(existing)
    return existing, "updated"


def mark_review_status(
    db: Session,
    candidate_id: int,
    status: str,
    reviewed_by: str | None = None,
    rejection_reason: str | None = None,
) -> ExternalImageCandidate:
    """Сменить статус review. 422 — неизвестный статус; 404 — нет кандидата."""
    if status not in ALLOWED_REVIEW_STATUSES:
        raise InvalidExternalImageReviewStatusError(status)
    candidate = get_candidate_by_id(db, candidate_id)
    if candidate is None:
        raise ExternalImageCandidateNotFoundError(candidate_id)
    candidate.review_status = status
    candidate.reviewed_at = _utcnow()
    candidate.reviewed_by = reviewed_by
    candidate.rejection_reason = rejection_reason
    db.commit()
    db.refresh(candidate)
    return candidate
